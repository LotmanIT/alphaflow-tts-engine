"""
AlphaFlow Creator — TTS Engine (edge-tts)
==========================================
Containerized FastAPI service that turns the 6-column production matrix
dialogue lines into per-scene MP3 audio tracks + a unified timing manifest.

Endpoints:
  GET  /health                    -> liveness probe
  POST /generate-audio            -> synthesize per-scene MP3s
  GET  /audio/{job_id}/{index}    -> stream a single scene MP3

Deploy:
  Render (free tier) — render.yaml at repo root, runtime docker
  or: docker build -t alphaflow-tts . && docker run -p 8000:8000 alphaflow-tts
"""
import re
import uuid
from typing import List, Optional

import edge_tts
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI(title="AlphaFlow TTS Engine", version="1.0.0")

# CORS open for the console (thin shell) + Notion embed; no secrets live here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Character -> voice binding. Michelle = default leading voice (Lokman's fave).
VOICE_MAP = {
    "aura": "en-US-MichelleNeural",
    "captain flow": "en-US-GuyNeural",
    "captain": "en-US-GuyNeural",
    "the host": "en-US-GuyNeural",
    "host": "en-US-GuyNeural",
    "the skeptic": "en-US-DavisNeural",
    "skeptic": "en-US-DavisNeural",
    "narrator": "en-US-AriaNeural",
}
DEFAULT_VOICE = "en-US-AriaNeural"

# Strip inline visual cues ([ZOOM], [OVERLAY: ...], [PATTERN INTERRUPT], [PiP], [ACTION]).
CUE_RE = re.compile(r"\[(ZOOM|PATTERN INTERRUPT|OVERLAY|PiP|ACTION|HOOK)[^\]]*\]", re.IGNORECASE)


class Scene(BaseModel):
    scene: str = ""
    role: str = ""
    content: str = ""


class GenerateRequest(BaseModel):
    scenes: List[Scene]
    voice_map: Optional[dict] = None


# In-memory cache: job_id -> list[bytes]. Ephemeral (fine for free-tier demo).
AUDIO_CACHE: dict = {}


def strip_cues(text: str) -> str:
    t = CUE_RE.sub("", text or "")
    return t.replace("\\|", "|").strip()


def voice_for_role(role: str, overrides: Optional[dict]) -> str:
    r = (role or "").strip().lower()
    if overrides:
        for k, v in overrides.items():
            if k.strip().lower() == r:
                return v
    for k, v in VOICE_MAP.items():
        if k in r:
            return v
    return DEFAULT_VOICE


async def synthesize(text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice)
    buf = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)


@app.get("/health")
async def health():
    return {"ok": True, "service": "AlphaFlow TTS Engine", "voices": len(VOICE_MAP) + 1}


@app.post("/generate-audio")
async def generate_audio(req: GenerateRequest):
    if not req.scenes:
        raise HTTPException(status_code=400, detail="no scenes")
    job_id = uuid.uuid4().hex
    chunks: list = []
    manifest: list = []
    for i, s in enumerate(req.scenes):
        text = strip_cues(s.content) or " "
        voice = voice_for_role(s.role, req.voice_map)
        mp3 = await synthesize(text, voice)
        chunks.append(mp3)
        manifest.append({
            "index": i,
            "scene": s.scene,
            "role": s.role,
            "voice": voice,
            "text": text,
            "bytes": len(mp3),
        })
    AUDIO_CACHE[job_id] = chunks
    return {
        "ok": True,
        "id": job_id,
        "audio": [{"index": i, "scene": s.scene, "role": s.role, "url": f"/audio/{job_id}/{i}"} for i, s in enumerate(req.scenes)],
        "manifest": manifest,
    }


@app.get("/audio/{job_id}/{index}")
async def get_audio(job_id: str, index: int):
    chunks = AUDIO_CACHE.get(job_id)
    if not chunks or index >= len(chunks):
        raise HTTPException(status_code=404, detail="audio not found")
    filename = f"scene-{index + 1}.mp3"
    return Response(
        content=chunks[index],
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )
