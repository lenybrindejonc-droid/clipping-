#!/usr/bin/env bash
# Lance le site sur http://localhost:8000
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then echo "Lance d'abord ./install.sh"; exit 1; fi
set -a; [ -f .env ] && . ./.env; set +a
if [[ "${ANTHROPIC_API_KEY:-}" != sk-ant-* ]]; then
  echo "⚠️  Pas de clé Claude valide dans .env → les moments seront choisis en mode basique (moins bon)."
fi
.venv/bin/pip install -q -r requirements.txt >/dev/null 2>&1 || true
.venv/bin/pip install -q -U yt-dlp >/dev/null 2>&1 || true   # YouTube change souvent
echo "🚀 Ouvre http://localhost:8000 dans ton navigateur (Ctrl+C pour arrêter)"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
