#!/usr/bin/env bash
# Télécharge une vidéo YouTube sur CET ordinateur, pour l'envoyer ensuite au site.
# Usage : ./telecharger.sh "https://www.youtube.com/watch?v=..."
set -e
cd "$(dirname "$0")"
if [ -z "${1:-}" ]; then echo 'Usage : ./telecharger.sh "https://www.youtube.com/watch?v=..."'; exit 1; fi
if [ ! -d .venv ]; then echo "Lance d'abord ./install.sh"; exit 1; fi
.venv/bin/pip install -q -U yt-dlp >/dev/null 2>&1 || true

# YouTube exige maintenant un moteur JavaScript : on l'installe une fois pour toutes
export PATH="$HOME/.local/bin:$PATH"
command -v deno >/dev/null 2>&1 || ./install_deno.sh >/dev/null 2>&1 || true

COOKIES=()
if [ -f cookies.txt ]; then COOKIES=(--cookies cookies.txt); echo "🍪 Cookies utilisés."; fi

mkdir -p ~/videos
if ! .venv/bin/yt-dlp -S "res:1080,vcodec:h264,ext:mp4" --merge-output-format mp4 \
     "${COOKIES[@]}" -o "$HOME/videos/%(title).80s.%(ext)s" "$1"; then
  echo
  echo "❌ YouTube a refusé le téléchargement."
  echo "   Si le message parle de « Sign in to confirm you are not a bot », il faut des cookies :"
  echo "   1. Dans Chrome, connecte-toi à YouTube (compte secondaire de préférence)."
  echo "   2. Installe l'extension « Get cookies.txt LOCALLY »."
  echo "   3. Sur youtube.com, exporte les cookies."
  echo "   4. Dans l'application Fichiers, mets cookies.txt dans Fichiers Linux puis clipping-"
  echo "   5. Relance cette commande."
  exit 1
fi
echo
echo "✅ Vidéo enregistrée dans le dossier « videos »."
ls -lh ~/videos | tail -3
echo
echo "👉 Dans ton navigateur, sur le site : « Choisir une vidéo sur mon ordinateur »,"
echo "   puis Fichiers Linux → videos → ta vidéo."
