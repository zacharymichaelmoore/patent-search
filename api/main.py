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
import requests

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


def analyze_with_ollama_sync(user_description, patent):
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
        with requests.post(
            OLLAMA_URL,
            json={"model": "llama3.1:8b", "prompt": prompt, "stream": True},
            stream=True,
            timeout=120
        ) as response:
            chunks = []
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if "response" in obj:
                        chunks.append(obj["response"])
                except json.JSONDecodeError:
                    continue
        full = "".join(chunks).strip()
        result = extract_json_from_text(full)
        if result and all(k in result for k in ("score", "level", "reason")):
            return result
        return {"score": None, "level": "Unknown", "reason": "Failed"}
    except Exception as e:
        return {"score": None, "level": "Unknown", "reason": f"Error: {e}"}


async def event_stream(user_description, top_k):
    try:
        yield json.dumps({"event": "log", "message": "[SEARCH] Starting embedding..."}) + "\n"

        qvec = await asyncio.to_thread(embed_text_sync, user_description)
        yield json.dumps({"event": "log", "message": "[SEARCH] Embedding complete"}) + "\n"

        patents = await asyncio.to_thread(qdrant_search, qvec, top_k)
        yield json.dumps({"event": "log", "message": f"[SEARCH] Found {len(patents)} patents"}) + "\n"

        for i, patent in enumerate(patents):
            analysis = await asyncio.to_thread(analyze_with_ollama_sync, user_description, patent)
            patent.update(analysis)
            yield json.dumps({"event": "result", "index": i, "result": patent}) + "\n"

        yield json.dumps({"event": "complete", "message": "Search complete"}) + "\n"
    except Exception as e:
        yield json.dumps({"event": "error", "message": str(e)}) + "\n"

# ---- ROUTES ----


@app.get("/", response_class=HTMLResponse)
async def serve_frontend(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/search")
async def search_api(request: Request):
    body = await request.json()
    user_description = body.get("userDescription", "")
    top_k = int(body.get("topK", 7))
    return StreamingResponse(event_stream(user_description, top_k), media_type="text/event-stream")


@app.get("/api/search")
async def search_stream(userDescription: str = "", topK: int = 7):
    """
    GET-based streaming endpoint for EventSource (used by frontend)
    """
    return StreamingResponse(
        event_stream(userDescription, topK),
        media_type="text/event-stream"
    )


@app.get("/export_csv")
async def export_csv(query: str = Query("", alias="userDescription"), topK: int = Query(7)):
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
