import asyncio
import json
import os
import re
import requests
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
import io
import csv

# ---- globals (loaded once) ----
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://172.17.0.1:11434/api/generate")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = "uspto_patents"

_qdrant = QdrantClient(url=QDRANT_URL)
_model = SentenceTransformer(EMBED_MODEL_NAME)
router = APIRouter(prefix="/api/search", tags=["search"])

# ---- helper: qdrant ----
def qdrant_search(query_vector, top_k=10):
    points = _qdrant.search(
        collection_name=QDRANT_COLLECTION,
        query_vector=query_vector,
        limit=top_k,
        with_payload=True,
    )

    results = []
    for p in points:
        payload = p.payload or {}
        patent_number = str(payload.get("patentNumber", "")).strip()

        # Ensure patent number starts with "US"
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

# ---- helper: embedding ----
def embed_text_sync(text):
    return _model.encode(text).tolist()

# ---- helper: robust JSON parser ----
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

# ---- helper: Ollama analyzer ----
def analyze_with_ollama_sync(user_description, patent):
    prompt = f"""
You are an expert patent analyst. Analyze the following patent and return ONLY a single JSON object.

USER DESCRIPTION:
{user_description}

PATENT TITLE:
{patent['title']}

ABSTRACT:
{patent['abstract']}

Respond only in JSON, following this exact schema:
{{
  "score": <integer from 0 to 100>,
  "level": "<Low|Medium|High>",
  "reason": "<short explanation>"
}}
No other text. No markdown, no commentary, only valid JSON.
""".strip()

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
                    elif isinstance(obj, str):
                        chunks.append(obj)
                except json.JSONDecodeError:
                    continue

        full = "".join(chunks).strip()
        result = extract_json_from_text(full)
        if result and all(k in result for k in ("score", "level", "reason")):
            return result

        return {"score": None, "level": "Unknown", "reason": "Failed"}

    except Exception as e:
        return {"score": None, "level": "Unknown", "reason": f"Error: {e}"}

# ---- streaming generator ----
async def event_stream(user_description, top_k):
    yield json.dumps({"event": "log", "message": "[SEARCH] Embedding complete"}) + "\n"

    qvec = await asyncio.to_thread(embed_text_sync, user_description)
    patents = await asyncio.to_thread(qdrant_search, qvec, top_k)

    yield json.dumps({"event": "log", "message": f"[SEARCH] Found {len(patents)} patents"}) + "\n"

    for i, patent in enumerate(patents):
        analysis = await asyncio.to_thread(analyze_with_ollama_sync, user_description, patent)
        patent.update(analysis)
        yield json.dumps({"event": "result", "index": i, "result": patent}) + "\n"

# ---- main streaming route ----
@router.post("")
async def search_patents(request: Request):
    body = await request.json()
    user_description = body.get("userDescription", "")
    top_k = int(body.get("topK", 10))
    return StreamingResponse(event_stream(user_description, top_k), media_type="text/event-stream")

# ---- new CSV route ----
@router.post("/csv")
async def search_patents_csv(request: Request):
    body = await request.json()
    user_description = body.get("userDescription", "")
    top_k = int(body.get("topK", 10))

    qvec = await asyncio.to_thread(embed_text_sync, user_description)
    patents = await asyncio.to_thread(qdrant_search, qvec, top_k)

    results = []
    for patent in patents:
        analysis = await asyncio.to_thread(analyze_with_ollama_sync, user_description, patent)
        patent.update(analysis)
        results.append(patent)

    # Create CSV in memory
    output = io.StringIO()
    fieldnames = ["title", "patentNumber", "filingDate", "score", "level", "reason", "googlePatentUrl"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for r in results:
        writer.writerow({f: r.get(f, "") for f in fieldnames})
    output.seek(0)

    headers = {"Content-Disposition": 'attachment; filename="results.csv"'}
    return StreamingResponse(io.BytesIO(output.getvalue().encode()), media_type="text/csv", headers=headers)
