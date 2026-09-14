#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/backend"
if [ ! -x ".venv/bin/python" ]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
