#!/usr/bin/env bash
# Télécharge une vidéo YouTube sur CET ordinateur, pour l'envoyer ensuite au site.
# Usage : ./telecharger.sh "https://www.youtube.com/watch?v=..."
set -e
cd "$(dirname "$0")"
if [ -z "${1:-}" ]; then echo 'Usage : ./telecharger.sh "https://www.youtube.com/watch?v=..."'; exit 1; fi
if [ ! -d .venv ]; then echo "Lance d'abord ./install.sh"; exit 1; fi
.venv/bin/pip install -q -U yt-dlp >/dev/null 2>&1 || true
mkdir -p ~/videos
.venv/bin/yt-dlp -S "res:1080,vcodec:h264,ext:mp4" --merge-output-format mp4 \
  -o "$HOME/videos/%(title).80s.%(ext)s" "$1"
echo
echo "✅ Vidéo enregistrée dans le dossier « videos »."
ls -lh ~/videos | tail -3
echo
echo "👉 Dans ton navigateur, sur le site : « Choisir une vidéo sur mon ordinateur »,"
echo "   puis Fichiers Linux → videos → ta vidéo."
