FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# No COPY README.md: it is untracked in this repo, so a COPY would fail the build.
# The image does not need it at runtime.

# Render injects $PORT at runtime (default 10000); Hugging Face Spaces expects 7860.
EXPOSE 7860 10000

# Shell form on purpose: the exec form would pass "${PORT:-7860}" to uvicorn literally.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
