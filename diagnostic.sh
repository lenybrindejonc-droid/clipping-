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

echo "--- cookies.txt ---"
found=""
for c in cookies.txt "$HOME/cookies.txt" "$HOME/Downloads/cookies.txt" \
         /mnt/chromeos/MyFiles/Downloads/cookies.txt \
         /mnt/chromeos/MyFiles/Téléchargements/cookies.txt; do
  if [ -f "$c" ]; then
    echo "trouvé   : $c ($(wc -l < "$c") lignes, $(grep -ci youtube "$c") lignes youtube)"
    grep -qi "SID\|LOGIN_INFO" "$c" && echo "session  : OUI (connecté)" || echo "session  : NON (pas connecté lors de l'export)"
    found="$c"; break
  fi
done
[ -z "$found" ] && echo "trouvé   : AUCUN"
echo "partage ChromeOS : $([ -d /mnt/chromeos ] && echo OUI || echo NON)"

echo "--- test des identités (lecture des infos seulement) ---"
COOKIES=(); [ -n "$found" ] && COOKIES=(--cookies "$found")
for client in default tv ios web_safari android mweb; do
  if [ "$client" = default ]; then ARGS=(); else ARGS=(--extractor-args "youtube:player_client=$client"); fi
  out=$(timeout 60 $YTDLP --skip-download --print "%(title)s" "${COOKIES[@]}" "${ARGS[@]}" "$URL" 2>&1)
  if [ $? -eq 0 ] && [ -n "$out" ]; then
    printf "%-11s : OK  (%s)\n" "$client" "$(echo "$out" | head -1 | cut -c1-40)"
  else
    printf "%-11s : ÉCHEC — %s\n" "$client" "$(echo "$out" | grep -o 'ERROR.*' | head -1 | cut -c1-90)"
  fi
done
echo "======================================="
