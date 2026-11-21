#!/usr/bin/env bash
# Assemble les téléchargements interrompus : yt-dlp récupère l'image (.fNNN.mp4) et le son
# (.fNNN.m4a) séparément, puis les fusionne. Si le téléchargement s'arrête avant la fusion,
# il reste ces morceaux + un fichier .temp.mp4 inutilisable. Ce script termine le travail.
# Usage : ./reparer.sh
set -e
cd "$(dirname "$0")"
VIDEOS=~/videos
[ -d "$VIDEOS" ] || { echo "❌ Pas de dossier videos."; exit 1; }

shopt -s nullglob
trouve=0

for video in "$VIDEOS"/*.f[0-9]*.mp4 "$VIDEOS"/*.f[0-9]*.webm; do
  base="${video%.f[0-9]*}"          # nom sans le .fNNN.ext
  nom=$(basename "$base")
  audio=""
  for a in "$base".f[0-9]*.m4a "$base".f[0-9]*.weba "$base".f[0-9]*.opus; do
    [ -f "$a" ] && audio="$a" && break
  done
  sortie="$base.mp4"

  if [ -f "$sortie" ] && [ ! -L "$sortie" ]; then
    echo "⏭️  « $nom » : la version finale existe déjà."
    continue
  fi
  trouve=1
  if [ -z "$audio" ]; then
    echo "⚠️  « $nom » : image trouvée mais pas le son. Retéléchargement nécessaire."
    continue
  fi

  echo "🔧 Assemblage de « $nom »…"
  echo "    image : $(du -h "$video" | cut -f1)   son : $(du -h "$audio" | cut -f1)"
  if ffmpeg -nostdin -loglevel error -y -i "$video" -i "$audio" \
       -map 0:v:0 -map 1:a:0 -c copy -movflags +faststart "$sortie.tmp.mp4"; then
    duree=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$sortie.tmp.mp4" 2>/dev/null || echo 0)
    if [ "${duree%.*}" -gt 5 ] 2>/dev/null; then
      mv -f "$sortie.tmp.mp4" "$sortie"
      echo "    ✅ $(du -h "$sortie" | cut -f1) — $((${duree%.*} / 60)) min"
      rm -f "$video" "$audio" "$base.temp.mp4" "$base".f[0-9]*.part
      echo "    🧹 morceaux supprimés"
    else
      rm -f "$sortie.tmp.mp4"
      echo "    ❌ résultat illisible : retéléchargement nécessaire"
    fi
  else
    rm -f "$sortie.tmp.mp4"
    echo "    ❌ assemblage impossible : retéléchargement nécessaire"
  fi
done

# Fichiers temporaires orphelins (sans morceaux à assembler) : ils ne servent à rien
for t in "$VIDEOS"/*.temp.mp4; do
  base="${t%.temp.mp4}"
  if [ ! -f "$base.mp4" ]; then
    echo "⚠️  « $(basename "$base") » : seul un fichier temporaire existe, il est inutilisable."
    echo "    Retéléchargement nécessaire :  ./telecharger.sh \"LIEN\""
  else
    rm -f "$t"
  fi
  trouve=1
done

[ "$trouve" = 0 ] && echo "✅ Rien à réparer : tous tes téléchargements sont complets."
echo
echo "📂 Vidéos utilisables :"
for f in "$VIDEOS"/*.mp4 "$VIDEOS"/*.mkv "$VIDEOS"/*.webm; do
  case "$f" in *.temp.mp4|*.f[0-9]*) continue ;; esac
  echo "   $(du -h "$f" | cut -f1)  $(basename "$f")"
done
