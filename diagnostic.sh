#!/usr/bin/env bash
# Vérifie tout ce qui concerne le téléchargement YouTube et affiche un bilan à copier-coller.
# Usage : ./diagnostic.sh "https://youtu.be/..."
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
URL="${1:-https://www.youtube.com/watch?v=jNQXAC9IVRw}"
YTDLP=.venv/bin/yt-dlp

echo "================ BILAN ================"
echo "yt-dlp   : $($YTDLP --version 2>/dev/null || echo ABSENT)"
echo "deno     : $(deno --version 2>/dev/null | head -1 || echo ABSENT)"

echo "--- cookies ---"
# Cherche un fichier de cookies (l'extension le nomme souvent www.youtube.com_cookies.txt)
find_cookies() {
  ls -t cookies.txt ./*cookies*.txt "$HOME"/*cookies*.txt "$HOME"/Downloads/*cookies*.txt \
     /mnt/chromeos/MyFiles/Downloads/*cookies*.txt \
     /mnt/chromeos/MyFiles/Téléchargements/*cookies*.txt \
     /mnt/chromeos/MyFiles/*/*cookies*.txt 2>/dev/null | head -1
}
found=$(find_cookies)
if [ -n "$found" ]; then
  echo "trouvé   : $found ($(wc -l < "$found") lignes, $(grep -ci youtube "$found") lignes youtube)"
  grep -qi "SID\|LOGIN_INFO" "$found" && echo "session  : OUI (connecté)" || echo "session  : NON (pas connecté lors de l'export)"
else
  echo "trouvé   : AUCUN"
  echo "fichiers .txt visibles dans les Téléchargements :"
  ls -t "$HOME"/Downloads/*.txt /mnt/chromeos/MyFiles/Downloads/*.txt \
     /mnt/chromeos/MyFiles/Téléchargements/*.txt 2>/dev/null | head -5 || echo "  (aucun)"
fi
echo "partage ChromeOS : $([ -d /mnt/chromeos ] && echo OUI || echo NON)"

echo "--- test des identités (lecture des infos seulement) ---"
COOKIES=(); [ -n "$found" ] && COOKIES=(--cookies "$found")
for client in default tv ios web_safari android mweb; do
  if [ "$client" = default ]; then ARGS=(); else ARGS=(--extractor-args "youtube:player_client=$client"); fi
  out=$(timeout 90 $YTDLP --skip-download --print "%(title)s" --remote-components ejs:github "${COOKIES[@]}" "${ARGS[@]}" "$URL" 2>&1)
  if [ $? -eq 0 ] && [ -n "$out" ]; then
    printf "%-11s : OK  (%s)\n" "$client" "$(echo "$out" | head -1 | cut -c1-40)"
  else
    printf "%-11s : ÉCHEC — %s\n" "$client" "$(echo "$out" | grep -o 'ERROR.*' | head -1 | cut -c1-90)"
  fi
done

echo "--- formats réellement proposés ---"
timeout 90 $YTDLP -F --remote-components ejs:github "${COOKIES[@]}" "$URL" 2>&1 | tail -12

echo "--- vidéo de référence (test indépendant) ---"
timeout 60 $YTDLP --skip-download --print "%(title)s" --remote-components ejs:github "${COOKIES[@]}" \
  "https://www.youtube.com/watch?v=jNQXAC9IVRw" 2>&1 | tail -2

echo "======================================="
