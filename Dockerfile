# ── Manim Render Service ──
# Builds from a standard Python slim image and installs Manim + all system
# dependencies explicitly. More reliable on Railway than the Manim base image.
FROM python:3.11-slim

# ── System dependencies ───────────────────────────────────────────────────────
# ffmpeg       – video encoding
# libcairo2    – 2D graphics (required by Manim)
# libpango     – text rendering
# pkg-config   – needed for Cairo build flags
# build-essential + python3-dev – compile any C-extension pip packages
# texlive-*    – minimal LaTeX for MathTex rendering
# dvipng       – LaTeX → PNG helper used by Manim
# cm-super     – Type1 fonts for LaTeX
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libcairo2-dev \
    libpango1.0-dev \
    pkg-config \
    python3-dev \
    build-essential \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-science \
    dvipng \
    cm-super \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python dependencies ───────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Railway sets PORT automatically; default to 8000
ENV PORT=8000
EXPOSE $PORT

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
