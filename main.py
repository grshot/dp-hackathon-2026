"""
Manim Render Service
====================
Receives Manim Python code + a scene class name, renders it to MP4 via
`manim render`, uploads the result to Vercel Blob, and returns the URL.

Environment variables required:
  BLOB_READ_WRITE_TOKEN  – Vercel Blob token (same one used by the Next.js app)
  RENDER_API_KEY         – Optional shared secret; clients send it as
                           X-Api-Key header. Leave empty to disable auth.
"""

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────

BLOB_TOKEN: str = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
API_KEY: str = os.environ.get("RENDER_API_KEY", "")  # empty = no auth

QUALITY_FLAGS = {
    "low": "-ql",       # 480p 15fps  – fastest, good for previews
    "medium": "-qm",    # 720p 30fps  – balanced (default)
    "high": "-qh",      # 1080p 60fps – slowest
    "preview": "-qp",   # 480p 15fps with preview window (headless-safe alias)
}

# ── Models ────────────────────────────────────────────────────────────────────

class RenderRequest(BaseModel):
    code: str = Field(..., description="Full Manim Python source code")
    scene: str = Field(..., description="Class name of the Scene to render, e.g. 'LinearTransformScene'")
    topic_slug: str = Field("unknown", description="Topic slug used as Blob path prefix")
    quality: str = Field("medium", description="Render quality: low | medium | high")


class RenderResponse(BaseModel):
    videoUrl: str
    duration: str
    code: str


class ErrorDetail(BaseModel):
    detail: str
    stderr: str | None = None


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Manim Render Service",
    description="Renders Manim animations to MP4 and stores them in Vercel Blob.",
    version="1.0.0",
)


@app.get("/health")
def health() -> dict:
    """Railway / uptime monitors ping this endpoint."""
    return {"status": "ok", "service": "manim-render"}


@app.post("/render", response_model=RenderResponse)
async def render(
    req: RenderRequest,
    x_api_key: str = Header(default=""),
) -> RenderResponse:
    """
    Render a Manim scene to MP4 and return a Vercel Blob URL.

    Steps:
      1. Validate auth (if RENDER_API_KEY is set)
      2. Write code to a temp file
      3. Run `manim render scene.py <SceneName> -q<quality>`
      4. Find the MP4 output
      5. Upload to Vercel Blob
      6. Clean up temp files
      7. Return { videoUrl, duration, code }
    """
    # ── 1. Auth ──────────────────────────────────────────────────────────────
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Api-Key")

    if not req.code.strip():
        raise HTTPException(status_code=400, detail="`code` must not be empty")
    if not req.scene.strip():
        raise HTTPException(status_code=400, detail="`scene` must not be empty")
    if req.quality not in QUALITY_FLAGS:
        raise HTTPException(
            status_code=400,
            detail=f"`quality` must be one of: {', '.join(QUALITY_FLAGS)}",
        )

    # ── 2. Temp workspace ────────────────────────────────────────────────────
    work_dir = Path(tempfile.mkdtemp(prefix="manim-"))
    scene_file = work_dir / "scene.py"
    media_dir = work_dir / "media"

    try:
        scene_file.write_text(req.code, encoding="utf-8")

        # ── 3. Render ─────────────────────────────────────────────────────────
        quality_flag = QUALITY_FLAGS[req.quality]
        cmd = [
            "manim", "render",
            str(scene_file),
            req.scene,
            quality_flag,
            "--format", "mp4",
            "--media_dir", str(media_dir),
            "--disable_caching",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 2-minute hard cap per render
            cwd=str(work_dir),
        )

        if result.returncode != 0:
            # Return the last 3 000 chars of stderr for debugging
            stderr_tail = result.stderr[-3_000:] if result.stderr else "(no stderr)"
            raise HTTPException(
                status_code=500,
                detail=f"Manim render failed (exit {result.returncode}): {stderr_tail}",
            )

        # ── 4. Find MP4 ───────────────────────────────────────────────────────
        mp4_files = sorted(media_dir.rglob("*.mp4"))
        if not mp4_files:
            raise HTTPException(
                status_code=500,
                detail="Render succeeded but no MP4 file was produced. Check scene name.",
            )

        mp4_path = mp4_files[0]
        mp4_bytes = mp4_path.read_bytes()

        # ── 4b. Get duration via ffprobe ──────────────────────────────────────
        duration = "unknown"
        try:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(mp4_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            secs = float(probe.stdout.strip())
            minutes = int(secs // 60)
            remaining = secs % 60
            duration = f"{minutes}:{remaining:04.1f}" if minutes else f"{secs:.1f}s"
        except Exception:
            pass  # duration remains "unknown"

        # ── 5. Upload to Vercel Blob ──────────────────────────────────────────
        if not BLOB_TOKEN:
            raise HTTPException(
                status_code=500,
                detail="BLOB_READ_WRITE_TOKEN is not configured on the server.",
            )

        blob_path = f"manim/{req.topic_slug}/{uuid.uuid4()}.mp4"

        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"https://blob.vercel-storage.com/{blob_path}",
                content=mp4_bytes,
                headers={
                    "Authorization": f"Bearer {BLOB_TOKEN}",
                    "x-content-type": "video/mp4",
                    "x-vercel-blob-content-type": "video/mp4",
                },
                timeout=90.0,
            )

        if resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=502,
                detail=f"Vercel Blob upload failed ({resp.status_code}): {resp.text[:500]}",
            )

        video_url: str = resp.json().get("url", "")
        if not video_url:
            raise HTTPException(
                status_code=502,
                detail=f"Vercel Blob returned no URL. Response: {resp.text[:500]}",
            )

        return RenderResponse(videoUrl=video_url, duration=duration, code=req.code)

    finally:
        # ── 6. Cleanup ────────────────────────────────────────────────────────
        shutil.rmtree(work_dir, ignore_errors=True)
