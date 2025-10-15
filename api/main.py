from fastapi import FastAPI, Request, Query
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from api.routes import extract_terms, generate_description, related_terms
import io
import csv
import asyncio
import json
import os
import re
import httpx
from typing import Optional, Dict, Any

def _safe_int_env(var_name: str, default: int, minimum: int = 1) -> int:
    raw_value = os.getenv(var_name, str(default))
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return max(default, minimum)
    return max(value, minimum)


def _safe_float_env(var_name: str, default: float) -> float:
    raw_value = os.getenv(var_name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default

# ---- GLOBAL CONFIG ----
app = FastAPI(title="Patent Search App")
app.include_router(extract_terms.router)
app.include_router(generate_description.router)
app.include_router(related_terms.router)
app.mount("/static", StaticFiles(directory="frontend"), name="static")
templates = Jinja2Templates(directory="frontend")

EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://172.17.0.1:11434/api/generate")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = "uspto_patents"
OLLAMA_CONCURRENCY = _safe_int_env("OLLAMA_CONCURRENCY", 128)
QDRANT_FETCH_COUNT = _safe_int_env("QDRANT_FETCH_COUNT", 5000)
HIGH_SCORE_THRESHOLD = _safe_int_env("HIGH_SCORE_THRESHOLD", 90)
MEDIUM_SCORE_THRESHOLD = _safe_int_env("MEDIUM_SCORE_THRESHOLD", 80)
ANALYSIS_PROGRESS_INTERVAL = _safe_int_env("ANALYSIS_PROGRESS_INTERVAL", 1)
OLLAMA_TIMEOUT_SECONDS = _safe_float_env("OLLAMA_TIMEOUT_SECONDS", 120.0)

_qdrant = QdrantClient(url=QDRANT_URL)
_model = SentenceTransformer(EMBED_MODEL_NAME)
HTTPX_LIMITS = httpx.Limits(
    max_connections=max(OLLAMA_CONCURRENCY * 8, 1),
    max_keepalive_connections=max(OLLAMA_CONCURRENCY, 1),
)
_httpx_client: Optional[httpx.AsyncClient] = None
_httpx_client_lock = asyncio.Lock()


async def get_httpx_client() -> httpx.AsyncClient:
    global _httpx_client
    if _httpx_client is None:
        async with _httpx_client_lock:
            if _httpx_client is None:
                _httpx_client = httpx.AsyncClient(
                    timeout=OLLAMA_TIMEOUT_SECONDS, limits=HTTPX_LIMITS
                )
    return _httpx_client


def format_sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

# ---- HELPERS ----

def embed_text_sync(text: str):
    return _model.encode(text).tolist()


def qdrant_search(query_vector, top_k=10):
    points = _qdrant.search(collection_name=QDRANT_COLLECTION,
                            query_vector=query_vector, limit=top_k, with_payload=True)
    results = []
    for p in points:
        payload = p.payload or {}
        patent_number = str(payload.get("patentNumber", "")).strip()
        if patent_number and not patent_number.upper().startswith("US"):
            patent_number = f"US{patent_number}"
        google_patent_url = f"https://patents.google.com/patent/{patent_number}/en" if patent_number else None
        results.append({
            "title": payload.get("title"),
            "abstract": payload.get("abstract"),
            "filingDate": payload.get("filingDate"),
            "patentNumber": patent_number,
            "googlePatentUrl": google_patent_url,
            "preview": (payload.get("abstract") or "")[:400],
            "file_path": payload.get("file_path"),
            "score": None,
            "reason": "Pending"
        })
    return results


def extract_json_from_text(text):
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        cleaned = re.sub(r'[\x00-\x1f]+', '', match.group(0))
        try:
            return json.loads(cleaned)
        except Exception:
            return None


async def analyze_patent_with_ollama_async(client: httpx.AsyncClient, user_description: str, patent: dict):
    """Analyzes a single patent asynchronously using httpx."""
    prompt = f"""
You are an expert patent analyst. Analyze the following patent and return ONLY a single JSON object.

USER DESCRIPTION:
{user_description}

PATENT TITLE:
{patent['title']}

ABSTRACT:
{patent['abstract']}

Respond only in JSON, following this schema:
{{
  "score": <integer from 0 to 100>,
  "reason": "<short explanation>"
}}
No extra text.
"""
    try:
        response = await client.post(
            OLLAMA_URL,
            json={
                "model": "llama3.1:8bgpu",
                "prompt": prompt,
                "stream": False
            },
            timeout=OLLAMA_TIMEOUT_SECONDS
        )
        response.raise_for_status()

        full_response_text = response.json().get("response", "")
        analysis_json = extract_json_from_text(full_response_text)

        if analysis_json and "score" in analysis_json:
            raw_score = analysis_json.get("score")
            try:
                score_value = float(raw_score)
            except (TypeError, ValueError):
                score_value = None

            if score_value is not None:
                patent["score"] = round(score_value, 2)
                if "reason" in analysis_json and analysis_json.get("reason"):
                    patent["reason"] = analysis_json.get("reason")
            else:
                patent.update({
                    "score": None,
                    "reason": "Failed to parse analysis."
                })
                return patent
        else:
            patent.update({
                "score": None,
                "reason": "Failed to parse analysis."
            })

        return patent

    except asyncio.CancelledError:
        raise
    except httpx.RequestError as e:
        print(f"Error analyzing patent {patent.get('patentNumber')}: {e}")
        patent.update({
            "score": None,
            "reason": f"Analysis timed out or failed: {e}"
        })
        return patent
    except Exception as e:
        print(
            f"General error analyzing patent {patent.get('patentNumber')}: {e}")
        patent.update({
            "score": None,
            "reason": f"An unexpected error occurred: {e}"
        })
        return patent


async def event_stream(user_description, top_k):
    try:
        yield format_sse("log", {"message": "[SEARCH] Starting embedding..."})
        qvec = await asyncio.to_thread(embed_text_sync, user_description)

        yield format_sse("log", {"message": "[SEARCH] Finding candidate patents..."})
        patents = await asyncio.to_thread(qdrant_search, qvec, QDRANT_FETCH_COUNT)

        if not patents:
            yield format_sse("log", {"message": "[SEARCH] No candidates found."})
            yield format_sse("complete", {"message": "Search complete", "results": 0, "analyzed": 0})
            return

        total_candidates = len(patents)
        yield format_sse("log", {
            "message": f"[SEARCH] Found {total_candidates} candidates, analyzing all with concurrency={OLLAMA_CONCURRENCY}..."
        })

        client = await get_httpx_client()
        analyzed_patents = []
        processed = 0
        semaphore = asyncio.Semaphore(OLLAMA_CONCURRENCY)

        async def analyze_with_limit(idx, patent):
            async with semaphore:
                analyzed = await analyze_patent_with_ollama_async(client, user_description, patent)
                return idx, analyzed

        tasks = [asyncio.create_task(analyze_with_limit(idx, patent))
                 for idx, patent in enumerate(patents)]

        # Wait for ALL analysis to complete - no early stopping
        for future in asyncio.as_completed(tasks):
            idx, analyzed_patent = await future
            processed += 1

            if ANALYSIS_PROGRESS_INTERVAL and processed % ANALYSIS_PROGRESS_INTERVAL == 0:
                yield format_sse("log", {
                    "message": f"[ANALYZE] Processed {processed}/{total_candidates} candidates"
                })

            # Collect ALL analyzed patents (even if score is low or None)
            analyzed_patents.append(analyzed_patent)

        # Sort by score (highest first), handle None scores by putting them at the end
        analyzed_patents.sort(
            key=lambda x: x.get("score") if x.get("score") is not None else -1,
            reverse=True
        )

        scored_patents = [p for p in analyzed_patents if p.get("score") is not None]
        high_confidence_total = [
            p for p in scored_patents if p["score"] >= HIGH_SCORE_THRESHOLD
        ]
        medium_confidence_total = [
            p for p in scored_patents if p["score"] >= MEDIUM_SCORE_THRESHOLD
        ]

        # Take top results above the high threshold
        top_results = high_confidence_total[:top_k]

        # Stream the top results to frontend
        for idx, result in enumerate(top_results):
            yield format_sse("result", {
                "index": idx,
                "result": result,
                "original_index": idx
            })

        yield format_sse("log", {
            "message": f"[SEARCH] Finished analysis. Showing top {len(top_results)} results."
        })
        yield format_sse("complete", {
            "message": "Search complete",
            "results": len(top_results),
            "analyzed": processed,
            "high_confidence": len(high_confidence_total),
            "medium_confidence": len(medium_confidence_total),
            "score_threshold": HIGH_SCORE_THRESHOLD,
            "total_candidates": total_candidates
        })

    except Exception as e:
        import traceback
        print(f"Error in event_stream: {traceback.format_exc()}")
        yield format_sse("error", {"message": str(e)})


@app.get("/", response_class=HTMLResponse)
async def serve_frontend(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/search")
async def search_api(request: Request):
    body = await request.json()
    user_description = body.get("userDescription", "")
    top_k = int(body.get("topK", 15))  # Changed default to 15
    return StreamingResponse(event_stream(user_description, top_k), media_type="text/event-stream")


@app.get("/api/search")
async def search_stream(userDescription: str = "", topK: int = 15):  # Changed default to 15
    """
    GET-based streaming endpoint for EventSource (used by frontend)
    """
    return StreamingResponse(
        event_stream(userDescription, topK),
        media_type="text/event-stream"
    )


@app.get("/export_csv")
# Changed default to 15
async def export_csv(query: str = Query("", alias="userDescription"), topK: int = Query(15)):
    qvec = await asyncio.to_thread(embed_text_sync, query)
    patents = await asyncio.to_thread(qdrant_search, qvec, topK)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(patents[0].keys()))
    writer.writeheader()
    writer.writerows(patents)
    output.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="results.csv"'}
    return StreamingResponse(output, media_type="text/csv", headers=headers)


@app.on_event("shutdown")
async def shutdown_http_client():
    global _httpx_client
    if _httpx_client is not None:
        await _httpx_client.aclose()
        _httpx_client = None


@app.get("/health")
def health():
    return {"status": "ok"}
