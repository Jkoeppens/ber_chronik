# Dockerfile — der neue Dienst (src/neu) samt Oberfläche
#
# Nicht das alte von Fly.io: das ist Dockerfile.local, baut nur Python, startet
# dev_server.py auf festem Port 8001 und kennt kein Node.
#
# Zwei Werkzeugketten, weil zwei gebraucht werden: Python für den Dienst, Node
# einmalig für frontend/build. Zur Laufzeit ist kein Node nötig — seit
# export/kern.py das Netzlayout mit networkx.spring_layout rechnet, gibt es
# keinen subprocess-Aufruf nach node mehr.

# ── Stufe 1: das Frontend ────────────────────────────────────────────────────
# Eigene Stufe, damit Node und node_modules nicht im Endabbild landen.
# frontend/build ist gitignoriert und muss deshalb hier entstehen; ohne es
# antwortet die Wurzel mit 503 statt mit einer Seite.
FROM node:22-slim AS frontend

WORKDIR /bau
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# ── Stufe 2: die Python-Abhängigkeiten ───────────────────────────────────────
FROM python:3.11-slim AS python-bau

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN python -m venv .venv

# Der CPU-Index für torch. Ohne ihn zieht pip auf amd64 den vollen
# CUDA-Stapel nach — gemessen im Railway-Bauprotokoll: nvidia-cublas,
# nvidia-cudnn, nvidia-cufft, nvidia-cusolver, nvidia-cusparse, nvidia-nccl,
# nvidia-nvjitlink, cuda-toolkit, triton. Auf einer Maschine ohne GPU.
COPY requirements.lock.txt .
RUN .venv/bin/pip install --upgrade pip \
 && .venv/bin/pip install \
      --extra-index-url https://download.pytorch.org/whl/cpu \
      -r requirements.lock.txt


# ── Stufe 3: das Abbild ──────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY --from=python-bau /app/.venv .venv/
COPY . .
COPY --from=frontend /bau/build ./frontend/build

# Die Modellgewichte aufs Laufwerk. urchade/gliner_multi sind 1,1 GB; ohne
# das liegen sie in /root/.cache und werden bei JEDEM Deploy neu geladen —
# gemessen auf Railway, sieben Sekunden für vier Dateien, ungedrosselt nur mit
# HF_TOKEN. Unter /data überleben sie den Neustart.
ENV HF_HOME=/data/huggingface

# Alles, was der Betrieb erzeugt, aufs Laufwerk: Datenbank, hochgeladene
# Rohdokumente, Exporte. Eine Variable für alle drei — src/neu/pfade.py leitet
# sie daraus ab, und src/generalized/config.py liest dieselbe, damit beide
# Systeme sich ein Laufwerk teilen. Fehlt die Datenbank beim Start, wird sie
# angelegt; das steht deutlich im Protokoll.
ENV DATA_ROOT=/data

EXPOSE 8000

# sh -c wegen ${PORT}: Railway reicht den Startbefehl nicht durch eine Shell,
# und uvicorn bekam am 17. Mai die Zeichenkette "${PORT:-8001}" als Portangabe.
# Genau das hat Commit fe3cb825 behoben, sechs Minuten bevor das damalige
# Dockerfile umbenannt wurde.
CMD ["sh", "-c", "PYTHONPATH=. .venv/bin/uvicorn src.neu.server:app --host 0.0.0.0 --port ${PORT:-8000} --log-level info"]
