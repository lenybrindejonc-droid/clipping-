#!/usr/bin/env bash
# Télécharge une vidéo YouTube sur CET ordinateur, pour l'envoyer ensuite au site.
# Usage : ./telecharger.sh "https://www.youtube.com/watch?v=..."
set -e
cd "$(dirname "$0")"
if [ -z "${1:-}" ]; then echo 'Usage : ./telecharger.sh "https://www.youtube.com/watch?v=..."'; exit 1; fi
if [ ! -d .venv ]; then echo "Lance d'abord ./install.sh"; exit 1; fi
.venv/bin/pip install -q -U yt-dlp >/dev/null 2>&1 || true

# YouTube exige maintenant un moteur JavaScript
export PATH="$HOME/.local/bin:$PATH"
command -v deno >/dev/null 2>&1 || ./install_deno.sh >/dev/null 2>&1 || true

# Cherche cookies.txt aux endroits habituels (y compris les Téléchargements de ChromeOS)
COOKIES=()
for c in cookies.txt "$HOME/cookies.txt" "$HOME/Downloads/cookies.txt" \
         /mnt/chromeos/MyFiles/Downloads/cookies.txt \
         /mnt/chromeos/MyFiles/Téléchargements/cookies.txt; do
  if [ -f "$c" ]; then
    cp -f "$c" cookies.txt 2>/dev/null || true
    COOKIES=(--cookies cookies.txt)
    echo "🍪 Cookies trouvés : $c"
    break
  fi
done
if [ ${#COOKIES[@]} -eq 0 ]; then
  echo "ℹ️  Aucun fichier cookies.txt trouvé — on essaie sans."
fi

mkdir -p ~/videos
OUT="$HOME/videos/%(title).80s.%(ext)s"
FORMAT='-S res:1080,vcodec:h264,ext:mp4 --merge-output-format mp4'

# On essaie plusieurs « identités » : YouTube en refuse certaines selon les jours
for client in default tv ios web_safari android mweb; do
  echo
  if [ "$client" = default ]; then
    echo "▶️  Tentative 1 (normale)…"
    ARGS=()
  else
    echo "▶️  Nouvelle tentative en se présentant comme : $client"
    ARGS=(--extractor-args "youtube:player_client=$client")
  fi
  if .venv/bin/yt-dlp $FORMAT "${COOKIES[@]}" "${ARGS[@]}" -o "$OUT" "$1"; then
    echo
    echo "✅ Vidéo enregistrée dans le dossier « videos »."
    ls -lh ~/videos | tail -3
    echo
    echo "👉 Sur le site : « Choisir une vidéo sur mon ordinateur »,"
    echo "   puis Fichiers Linux → videos → ta vidéo."
    exit 0
  fi
done

echo
echo "❌ YouTube a refusé le téléchargement avec toutes les méthodes."
if [ ${#COOKIES[@]} -eq 0 ]; then
  echo "   → Il te faut des cookies YouTube :"
  echo "     1. Dans Chrome, connecte-toi à YouTube (compte secondaire de préférence)."
  echo "     2. Installe l'extension « Get cookies.txt LOCALLY »."
  echo "     3. Sur youtube.com, clique sur l'extension puis Export."
  echo "     4. Laisse le fichier dans Téléchargements : le script le trouvera tout seul."
  echo "     5. Relance cette commande."
else
  echo "   → Tes cookies n'ont pas suffi. Vérifie que tu étais bien CONNECTÉ à YouTube"
  echo "     au moment de l'export, puis refais l'export et relance."
  echo "     Vérification rapide : grep -c youtube cookies.txt   (doit afficher plus de 5)"
fi
exit 1
