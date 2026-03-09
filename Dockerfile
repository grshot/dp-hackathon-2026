# ── Manim Render Service ──
# Uses the ManimCommunity image from Docker Hub (public, no auth required).
# Pre-installed: Python 3, Manim, LaTeX, Cairo, ffmpeg, ffprobe.
FROM manimcommunity/manim:stable

WORKDIR /app

# Install Python web service deps
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY main.py .

# Railway / Vercel / Cloud Run use PORT env var; default to 8000
ENV PORT=8000

EXPOSE $PORT

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
