# manim-service

A lightweight Python microservice that renders [Manim](https://www.manim.community/) animations to MP4 and stores them in Vercel Blob. Used by the main Next.js app to generate math animations for learning topics.

## How it works

```
POST /render  { code, scene, topic_slug, quality }
  → writes code to /tmp/scene.py
  → runs: manim render scene.py <SceneName> -q<quality>
  → uploads MP4 to Vercel Blob
  → returns { videoUrl, duration, code }
```

## Local development

```bash
# 1. Install Python deps (Python 3.10+ required)
pip install -r requirements.txt

# 2. You also need a local Manim install:
#    https://docs.manim.community/en/stable/installation.html
#    macOS: brew install manim
#    Linux: pip install manim (+ system deps: ffmpeg, latex, cairo)

# 3. Copy and fill env vars
cp .env.example .env

# 4. Start the server
uvicorn main:app --reload --port 8000

# 5. Test it
curl -X POST http://localhost:8000/render \
  -H "Content-Type: application/json" \
  -d '{
    "code": "from manim import *\nclass Demo(Scene):\n    def construct(self):\n        t = MathTex(r\"E = mc^2\").scale(2)\n        self.play(Write(t))\n        self.wait()",
    "scene": "Demo",
    "topic_slug": "test",
    "quality": "low"
  }'
```

## Deploying to Railway

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Select this repo
3. Set **Root Directory** to `manim-service`
4. Railway auto-detects the `Dockerfile` and builds it
5. Add environment variables in the Railway dashboard:

| Variable | Value |
|---|---|
| `BLOB_READ_WRITE_TOKEN` | Your Vercel Blob token (same as in Next.js) |
| `RENDER_API_KEY` | A secret string (share this with the Next.js app) |

6. Copy the Railway public URL (e.g. `https://manim-service-prod.up.railway.app`)
7. Add to the Next.js app's env:

```bash
# .env.local  (and in Vercel dashboard)
MANIM_SERVICE_URL=https://manim-service-prod.up.railway.app
MANIM_API_KEY=<same secret as RENDER_API_KEY>
```

## API reference

### `GET /health`

Returns `{ "status": "ok" }`. Used by Railway health checks.

### `POST /render`

**Headers:**
- `Content-Type: application/json`
- `X-Api-Key: <RENDER_API_KEY>` — required if `RENDER_API_KEY` is set on the server

**Request body:**

```json
{
  "code": "from manim import *\nclass MyScene(Scene):\n    def construct(self):\n        ...",
  "scene": "MyScene",
  "topic_slug": "linear-algebra",
  "quality": "medium"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `code` | string | required | Full Manim Python source |
| `scene` | string | required | Scene class name to render |
| `topic_slug` | string | `"unknown"` | Used as Blob path prefix (`manim/{slug}/uuid.mp4`) |
| `quality` | string | `"medium"` | `low` / `medium` / `high` |

**Response `200`:**

```json
{
  "videoUrl": "https://blob.vercel-storage.com/manim/linear-algebra/uuid.mp4",
  "duration": "8.3s",
  "code": "from manim import *\n..."
}
```

**Errors:** Standard FastAPI JSON `{ "detail": "..." }` with appropriate HTTP status codes.

## Quality guide

| Quality | Resolution | FPS | Typical render time |
|---|---|---|---|
| `low` | 480p | 15 | ~15s |
| `medium` | 720p | 30 | ~30–60s |
| `high` | 1080p | 60 | ~60–120s |

Use `low` for quick previews / demos, `medium` for production.

## Base Docker image

`ghcr.io/manimcommunity/manim:stable` ships with Python 3, Manim, LaTeX, Cairo, ffmpeg, and all system dependencies pre-installed — no extra system packages needed.
