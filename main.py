"""
Manim Render Service
====================
Receives Manim Python code + a scene class name, renders it to MP4 via
`manim render`, and returns the raw video bytes.

The caller (Next.js API route) is responsible for uploading to Vercel Blob.
This keeps BLOB_READ_WRITE_TOKEN out of the Railway environment entirely.

Environment variables:
  RENDER_API_KEY  – Optional shared secret sent as X-Api-Key header.
                    Leave empty to disable auth.
"""

import base64
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────

API_KEY: str = os.environ.get("RENDER_API_KEY", "")  # empty = no auth

QUALITY_FLAGS = {
    "low": "-ql",       # 480p 15fps  – fastest, good for previews
    "medium": "-qm",    # 720p 30fps  – balanced
    "high": "-qh",      # 1080p 60fps – slowest
    "preview": "-qp",   # 480p 15fps
}

# ── Models ────────────────────────────────────────────────────────────────────

class RenderRequest(BaseModel):
    code: str = Field(..., description="Full Manim Python source code")
    scene: str = Field(..., description="Scene class name to render")
    topic_slug: str = Field("unknown", description="Used as filename prefix")
    quality: str = Field("low", description="Render quality: low | medium | high")


# ── Code sanitizer ────────────────────────────────────────────────────────────

def sanitize_manim_code(code: str) -> str:
    """
    Replace LaTeX-dependent Manim classes (MathTex, Tex) with Text()
    so renders work without a TeX installation.
    """
    # MathTex → Text
    code = re.sub(r'\bMathTex\s*\(', 'Text(', code)
    # Tex( → Text(  (word boundary avoids hitting Context, Latex, etc.)
    code = re.sub(r'\bTex\s*\(', 'Text(', code)

    # Strip raw-string prefix: r"..." → "..."  r'...' → '...'
    code = re.sub(r'\br(""")', r'\1', code)
    code = re.sub(r"\br(''')", r'\1', code)
    code = re.sub(r'\br(")', r'\1', code)
    code = re.sub(r"\br(')", r'\1', code)

    # Remove LaTeX backslash sequences inside double-quoted strings
    def strip_latex_bs(m: re.Match) -> str:
        inner = m.group(1)
        inner = re.sub(r'\\([a-zA-Z]+)', r'\1 ', inner)   # \frac → frac
        inner = re.sub(r'[{}^_]', '', inner)               # remove {, }, ^, _
        return f'"{inner}"'

    code = re.sub(r'"((?:[^"\\]|\\.)*)"', strip_latex_bs, code)
    return code


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Manim Render Service",
    description="Renders Manim animations to MP4 and returns raw binary.",
    version="2.0.0",
)


@app.get("/health")
def health() -> dict:
    """Railway / uptime monitors ping this endpoint."""
    return {"status": "ok", "service": "manim-render"}


@app.post("/render")
async def render(
    req: RenderRequest,
    x_api_key: str = Header(default=""),
) -> Response:
    """
    Render a Manim scene and return the raw MP4 bytes.

    Response headers:
      Content-Type: video/mp4
      X-Duration:   human-readable duration string (e.g. "12.3s")
      X-Code:       base64-encoded sanitized source code
    """
    # ── Auth ──────────────────────────────────────────────────────────────────
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

    work_dir = Path(tempfile.mkdtemp(prefix="manim-"))
    scene_file = work_dir / "scene.py"
    media_dir = work_dir / "media"

    try:
        # Sanitize → write
        sanitized_code = sanitize_manim_code(req.code)
        scene_file.write_text(sanitized_code, encoding="utf-8")

        # Render
        cmd = [
            "manim", "render",
            str(scene_file),
            req.scene,
            QUALITY_FLAGS[req.quality],
            "--format", "mp4",
            "--media_dir", str(media_dir),
            "--disable_caching",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(work_dir),
        )
        if result.returncode != 0:
            stderr_tail = result.stderr[-3_000:] if result.stderr else "(no stderr)"
            raise HTTPException(
                status_code=500,
                detail=f"Manim render failed (exit {result.returncode}): {stderr_tail}",
            )

        # Find MP4
        mp4_files = sorted(media_dir.rglob("*.mp4"))
        if not mp4_files:
            raise HTTPException(
                status_code=500,
                detail="Render succeeded but no MP4 was produced — check scene name.",
            )
        mp4_bytes = mp4_files[0].read_bytes()

        # Duration via ffprobe
        duration = "unknown"
        try:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(mp4_files[0]),
                ],
                capture_output=True, text=True, timeout=10,
            )
            secs = float(probe.stdout.strip())
            minutes = int(secs // 60)
            remaining = secs % 60
            duration = f"{minutes}:{remaining:04.1f}" if minutes else f"{secs:.1f}s"
        except Exception:
            pass

        # Return raw bytes — caller uploads to Blob
        return Response(
            content=mp4_bytes,
            media_type="video/mp4",
            headers={
                "X-Duration": duration,
                "X-Code": base64.b64encode(sanitized_code.encode()).decode(),
            },
        )

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
