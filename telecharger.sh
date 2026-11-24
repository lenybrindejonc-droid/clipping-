#!/usr/bin/env bash
# Télécharge une vidéo YouTube sur CET ordinateur, pour l'envoyer ensuite au site.
# Usage : ./telecharger.sh "https://www.youtube.com/watch?v=..."  (ou un lien twitch.tv/videos/...)
set -e
cd "$(dirname "$0")"
if [ -z "${1:-}" ]; then echo 'Usage : ./telecharger.sh "https://www.youtube.com/watch?v=..."'; exit 1; fi
if [ ! -d .venv ]; then echo "Lance d'abord ./install.sh"; exit 1; fi
.venv/bin/pip install -q -U yt-dlp yt-dlp-ejs >/dev/null 2>&1 || true

# YouTube exige maintenant un moteur JavaScript
export PATH="$HOME/.local/bin:$PATH"
command -v deno >/dev/null 2>&1 || ./install_deno.sh >/dev/null 2>&1 || true

# Cherche un fichier de cookies (l'extension le nomme souvent www.youtube.com_cookies.txt)
find_cookies() {
  ls -t cookies.txt ./*cookies*.txt "$HOME"/*cookies*.txt "$HOME"/Downloads/*cookies*.txt \
     /mnt/chromeos/MyFiles/Downloads/*cookies*.txt \
     /mnt/chromeos/MyFiles/Téléchargements/*cookies*.txt \
     /mnt/chromeos/MyFiles/*/*cookies*.txt 2>/dev/null | head -1
}

COOKIES=()
found=$(find_cookies)
if [ -n "$found" ]; then
  COOKIES=(--cookies "$found")   # on utilise le fichier tel quel (pas de copie : évite les doublons)
  age=$(( ($(date +%s) - $(stat -c %Y "$found")) / 3600 ))
  echo "🍪 Cookies : $found ($(grep -ci youtube "$found") lignes youtube, exportés il y a ${age} h)"
  [ "$age" -gt 48 ] && echo "   ⚠️  Ils datent : si ça échoue, refais un export (méthode navigation privée)."
else
  echo "ℹ️  Aucun fichier de cookies trouvé — on essaie sans."
fi

mkdir -p ~/videos ~/videos/.encours
# Les fichiers intermédiaires restent dans .encours : seule la vidéo terminée arrive
# dans videos, pour ne plus confondre un téléchargement inachevé avec une vraie vidéo.
OUT="%(title).80s.%(ext)s"
CHEMINS=(-P "home:$HOME/videos" -P "temp:$HOME/videos/.encours")
# 1080 par défaut. Ne PAS descendre à 720 pour les podcasts : le cadrage 9:16 ne garde qu'une
# bande étroite de l'image, une source 720p donne des clips flous. QUALITE=1440 si la vidéo existe en 1440p.
QUALITE="${QUALITE:-1080}"
echo "📺 Qualité visée : ${QUALITE}p"
FORMAT="-S res:${QUALITE},vcodec:h264,ext:mp4 --merge-output-format mp4"
EJS=(--remote-components ejs:github)   # solveur des défis JavaScript de YouTube

# Peu de tentatives : chaque essai raté rend YouTube plus méfiant envers ton adresse.
# Pour tout essayer malgré tout : TOUT=1 ./telecharger.sh "lien"
CLIENTS="default tv"
[ "${TOUT:-0}" = "1" ] && CLIENTS="default tv ios web_safari android mweb"
for client in $CLIENTS; do
  echo
  if [ "$client" = default ]; then
    echo "▶️  Tentative 1 (normale)…"
    ARGS=()
  else
    echo "▶️  Nouvelle tentative en se présentant comme : $client"
    ARGS=(--extractor-args "youtube:player_client=$client")
  fi
  if .venv/bin/yt-dlp $FORMAT "${EJS[@]}" "${COOKIES[@]}" "${ARGS[@]}" "${CHEMINS[@]}" -o "$OUT" "$1"; then
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
case "$1" in *twitch.tv*)
  echo "❌ Twitch a refusé le téléchargement."
  echo "   → Vérifie que le lien s'ouvre bien (VOD pas supprimée, pas réservée aux abonnés)."
  echo "   → Les VOD Twitch s'effacent après quelques jours : prends les plus récentes."
  exit 1;;
esac
echo "❌ YouTube a refusé le téléchargement avec toutes les méthodes."
if ls ~/videos/.encours/* >/dev/null 2>&1; then
  echo "   💡 Un téléchargement précédent a laissé des morceaux : ./reparer.sh peut les assembler."
fi
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
