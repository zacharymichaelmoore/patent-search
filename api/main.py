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

_qdrant = QdrantClient(url=QDRANT_URL)
_model = SentenceTransformer(EMBED_MODEL_NAME)

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
            "level": "Unknown",
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
  "level": "<Low|Medium|High>",
  "reason": "<short explanation>"
}}
No extra text.
"""
    try:
        response = await client.post(
            OLLAMA_URL,
            json={
                "model": "llama3.1:8b",
                "prompt": prompt,
                "stream": False
            },
            timeout=120.0
        )
        response.raise_for_status()

        full_response_text = response.json().get("response", "")
        analysis_json = extract_json_from_text(full_response_text)

        if analysis_json and all(k in analysis_json for k in ("score", "level", "reason")):
            patent.update(analysis_json)
        else:
            patent.update({"score": None, "level": "Unknown",
                          "reason": "Failed to parse analysis."})

        return patent

    except httpx.RequestError as e:
        print(f"Error analyzing patent {patent.get('patentNumber')}: {e}")
        patent.update({"score": None, "level": "Unknown",
                      "reason": f"Analysis timed out or failed: {e}"})
        return patent
    except Exception as e:
        print(
            f"General error analyzing patent {patent.get('patentNumber')}: {e}")
        patent.update({"score": None, "level": "Unknown",
                      "reason": f"An unexpected error occurred: {e}"})
        return patent


async def event_stream(user_description, top_k):
    try:
        yield json.dumps({"event": "log", "message": "[SEARCH] Starting embedding..."}) + "\n"
        qvec = await asyncio.to_thread(embed_text_sync, user_description)

        yield json.dumps({"event": "log", "message": "[SEARCH] Finding candidate patents..."}) + "\n"
        # Fetch more candidates to filter from
        fetch_count = max(top_k * 5, 50)
        patents = await asyncio.to_thread(qdrant_search, qvec, fetch_count)

        yield json.dumps({"event": "log", "message": f"[SEARCH] Found {len(patents)} candidates, analyzing in parallel..."}) + "\n"

        analyzed_patents = []
        async with httpx.AsyncClient() as client:
            tasks = [
                analyze_patent_with_ollama_async(
                    client, user_description, patent)
                for patent in patents
            ]

            analyzed_patents = await asyncio.gather(*tasks)

        high_relevance_patents = [
            p for p in analyzed_patents
            if p.get("score") is not None and p["score"] >= 80
        ]

        high_relevance_patents.sort(
            key=lambda x: x.get('score', 0), reverse=True)

        final_patents = high_relevance_patents[:top_k]

        yield json.dumps({"event": "log", "message": f"[SEARCH] Found {len(final_patents)} high-relevance patents (80+ score)"}) + "\n"

        for i, patent in enumerate(final_patents):
            yield json.dumps({"event": "result", "index": i, "result": patent}) + "\n"
            await asyncio.sleep(0.01)

        yield json.dumps({"event": "complete", "message": "Search complete"}) + "\n"

    except Exception as e:
        import traceback
        print(f"Error in event_stream: {traceback.format_exc()}")
        yield json.dumps({"event": "error", "message": str(e)}) + "\n"


@app.get("/", response_class=HTMLResponse)
async def serve_frontend(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/search")
async def search_api(request: Request):
    body = await request.json()
    user_description = body.get("userDescription", "")
    top_k = int(body.get("topK", 100))
    return StreamingResponse(event_stream(user_description, top_k), media_type="text/event-stream")


@app.get("/api/search")
async def search_stream(userDescription: str = "", topK: int = 100):
    """
    GET-based streaming endpoint for EventSource (used by frontend)
    """
    return StreamingResponse(
        event_stream(userDescription, topK),
        media_type="text/event-stream"
    )


@app.get("/export_csv")
async def export_csv(query: str = Query("", alias="userDescription"), topK: int = Query(100)):
    qvec = await asyncio.to_thread(embed_text_sync, query)
    patents = await asyncio.to_thread(qdrant_search, qvec, topK)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(patents[0].keys()))
    writer.writeheader()
    writer.writerows(patents)
    output.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="results.csv"'}
    return StreamingResponse(output, media_type="text/csv", headers=headers)


@app.get("/health")
def health():
    return {"status": "ok"}
