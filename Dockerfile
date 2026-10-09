# Kompletné prostredie vrátane slovenského OCR. (Nebolo zostavené v prostredí, kde vznikol kód.)
#   docker build -t anonymizer-sk .
#   docker run --rm -it -v "$PWD/data:/data" -e ANON_PASSPHRASE anonymizer-sk \
#       anonymize /data/vstup -o /data/vystup --mode reversible
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-slk tesseract-ocr-eng poppler-utils fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt
COPY anonymizer_sk ./anonymizer_sk
COPY tests ./tests

# Stiahne NER model do obrazu, aby kontajner bežal offline
RUN python -c "from transformers import pipeline; pipeline('token-classification', model='crabz/slovakbert-ner')"
ENV HF_HUB_OFFLINE=1

ENTRYPOINT ["python", "-m", "anonymizer_sk"]
