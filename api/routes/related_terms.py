import os
import json
import re
import requests
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict

router = APIRouter(prefix="/api/get-related-terms", tags=["related"])

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://172.17.0.1:11434/api/generate")

class RelatedTermsRequest(BaseModel):
    terms: List[str]

def extract_json_array(text: str):
    match = re.search(r'\[[\s\S]*?\]', text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

async def get_synonyms_for_term(term: str) -> List[str]:
    prompt = f"""Generate 3-5 technical synonyms or closely related terms for: "{term}"

Return ONLY a JSON array of strings. No explanations, no markdown.
Example: ["synonym1", "synonym2", "synonym3"]

Do NOT include the original term.
JSON array:
""".strip()

    try:
        with requests.post(
            OLLAMA_URL,
            json={"model": "llama3.1:8b", "prompt": prompt, "stream": True},
            stream=True,
            timeout=30
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
        
        full_text = "".join(chunks).strip()
        result = extract_json_array(full_text)
        
        if result and isinstance(result, list):
            return [s for s in result if isinstance(s, str)][:5]
        
        return []
        
    except Exception as e:
        print(f"Error getting synonyms for '{term}': {e}")
        return []

@router.post("")
async def get_related_terms(request: RelatedTermsRequest):
    all_related: Dict[str, List[str]] = {}
    
    for term in request.terms:
        synonyms = await get_synonyms_for_term(term)
        all_related[term] = synonyms
    
    return all_related
