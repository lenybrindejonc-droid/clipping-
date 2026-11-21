#!/usr/bin/env bash
# Découpe une vidéo longue en parties, pour des envois courts et fiables.
# Usage : ./decouper.sh ~/videos/ma_video.mp4 [minutes_par_partie]
set -e
cd "$(dirname "$0")"
FICHIER="${1:-}"
MINUTES="${2:-30}"
if [ ! -f "$FICHIER" ]; then
  echo 'Usage : ./decouper.sh ~/videos/ma_video.mp4 [minutes_par_partie]'
  echo "Vidéos disponibles :"; ls -1sh ~/videos 2>/dev/null | tail -n +2 | head -10
  exit 1
fi
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
