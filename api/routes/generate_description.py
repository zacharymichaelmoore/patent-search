import os
import json
import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/generate-description", tags=["generate"])

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://172.17.0.1:11434/api/generate")

class GenerateRequest(BaseModel):
    prompt: str

ASYNC_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))


async def generate_stream(prompt: str):
    full_prompt = f"""You are a patent attorney helping draft a provisional patent application.

Based on this brief idea, write a detailed technical description (300-500 words) that includes:
- Technical overview and purpose
- Key components and how they work
- Novel aspects and advantages
- Potential applications

User's invention idea:
{prompt}

Write a professional provisional patent description:
""".strip()

    try:
        async with httpx.AsyncClient(timeout=ASYNC_TIMEOUT) as client:
            async with client.stream(
                "POST",
                OLLAMA_URL,
                json={
                    "model": "llama3.1-8gpu:latest",
                    "prompt": full_prompt,
                    "stream": True,
                },
            ) as response:
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("done"):
                        break
                    chunk = obj.get("response")
                    if chunk:
                        yield chunk
    except Exception as e:
        yield f"\n\n[Error: {e}]"

@router.post("")
async def generate_description(request: GenerateRequest):
    return StreamingResponse(
        generate_stream(request.prompt),
        media_type="text/plain"
    )
