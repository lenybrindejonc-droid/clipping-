#!/usr/bin/env bash
# Installe tout ce qu'il faut (Debian / Ubuntu / Chromebook Linux)
set -e
cd "$(dirname "$0")"
sudo apt update
sudo apt install -y ffmpeg python3-venv python3-full
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
./install_deno.sh || true   # moteur JavaScript exigé par YouTube
[ -f .env ] || cp .env.example .env
echo
echo "✅ Installation terminée."
echo "👉 Mets ta clé Claude dans le fichier .env (ligne ANTHROPIC_API_KEY=...)"
echo "👉 Puis lance : ./start.sh"
