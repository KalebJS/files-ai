FROM python:3.13-slim

ARG INSTALL_OCR=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && if [ "$INSTALL_OCR" = "true" ]; then apt-get install -y --no-install-recommends tesseract-ocr; fi \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

RUN useradd -m -u 10001 appuser
USER appuser

CMD ["python", "-m", "files_ai"]
