#!/usr/bin/env bash
# Découpe une vidéo longue en parties, pour des envois courts et fiables.
# Usage : ./decouper.sh ~/videos/ma_video.mp4 [minutes_par_partie]
set -e
cd "$(dirname "$0")"
MINUTES="${2:-30}"
# Sans argument : on prend la vidéo la plus récente du dossier videos
FICHIER="${1:-$(ls -t ~/videos/*.mp4 ~/videos/*.mkv ~/videos/*.webm 2>/dev/null | head -1)}"
if [ -z "$FICHIER" ] || [ ! -f "$FICHIER" ]; then
  echo "❌ Aucune vidéo trouvée dans le dossier videos."
  echo "   Contenu actuel :"
  ls -1sh ~/videos 2>/dev/null | tail -n +2 | head -10 || echo "   (le dossier n'existe pas encore)"
  echo
  echo "   Télécharge d'abord une vidéo :  ./telecharger.sh \"LIEN\""
  exit 1
fi
echo "📹 Vidéo : $FICHIER ($(du -h "$FICHIER" | cut -f1))"
NOM=$(basename "${FICHIER%.*}")
DEST=~/videos/parties
mkdir -p "$DEST"
echo "✂️  Découpage de « $NOM » en parties de $MINUTES minutes (sans perte de qualité)…"
ffmpeg -nostdin -loglevel error -i "$FICHIER" -c copy -map 0 -f segment \
  -segment_time $((MINUTES * 60)) -reset_timestamps 1 \
  "$DEST/${NOM}_partie%02d.mp4"
echo
echo "✅ Parties créées :"
ls -1sh "$DEST" | grep "$NOM" || true
echo
echo "👉 Envoie-les une par une au site (Fichiers Linux → videos → parties)."
echo "   Chaque partie donne ses propres clips."
