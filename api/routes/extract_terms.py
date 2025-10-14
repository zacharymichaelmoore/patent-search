import json
import re
import os
import requests
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/extract-terms", tags=["extract"])

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://172.17.0.1:11434/api/generate")

class ExtractTermsRequest(BaseModel):
    documentText: str

def extract_json_from_text(text: str):
    """Extract JSON from Ollama response that may contain markdown or extra text"""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        # Try to clean control characters
        cleaned = re.sub(r'[\x00-\x1f]+', '', match.group(0))
        try:
            return json.loads(cleaned)
        except Exception:
            return None

@router.post("")
async def extract_terms(request: ExtractTermsRequest):
    """
    Extract device, technology, and subject terms from patent description text.
    Uses Ollama (llama3.1:8b) for intelligent term extraction.
    """
    document_text = request.documentText
    
    if not document_text or len(document_text.strip()) < 20:
        return {
            "deviceTerms": [],
            "technologyTerms": [],
            "subjectTerms": []
        }
    
    prompt = f"""
Extract key technical terms from this patent description and categorize them.

Return ONLY a JSON object in this exact format (no markdown, no commentary):
{{
  "deviceTerms": ["physical devices, hardware, instruments"],
  "technologyTerms": ["methods, processes, algorithms, techniques"],
  "subjectTerms": ["application domains, fields, purposes"]
}}

Rules:
- Extract 3-7 terms per category
- Use singular form (e.g., "battery" not "batteries")
- Be specific and technical
- No generic terms like "system" or "method"

Patent Description:
{document_text[:2000]}

JSON output:
""".strip()

    try:
        # Stream request to Ollama
        with requests.post(
            OLLAMA_URL,
            json={"model": "llama3.1:8b", "prompt": prompt, "stream": True},
            stream=True,
            timeout=60
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
        result = extract_json_from_text(full_text)
        
        if result and all(k in result for k in ("deviceTerms", "technologyTerms", "subjectTerms")):
            return result
        
        # Fallback if parsing fails
        return {
            "deviceTerms": [],
            "technologyTerms": [],
            "subjectTerms": []
        }
        
    except Exception as e:
        print(f"Error extracting terms: {e}")
        return {
            "deviceTerms": [],
            "technologyTerms": [],
            "subjectTerms": []
        }
