# ── Manim Render Service ──
# Extends the official ManimCommunity image which already has:
#   Python 3, Manim + all Python deps, LaTeX, Cairo, ffmpeg, ffprobe
FROM ghcr.io/manimcommunity/manim:stable

WORKDIR /app

# Install Python web service deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Railway / Vercel / Cloud Run use PORT env var; default to 8000
ENV PORT=8000

EXPOSE $PORT

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
