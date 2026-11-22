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

  taille_mo=$(du -m "$video" | cut -f1)
  besoin=$(( $(du -m "$video" | cut -f1) + $(du -m "$audio" | cut -f1) + 200 ))
  libre=$(df -m ~ | tail -1 | awk '{print $4}')
  if [ "$libre" -lt "$besoin" ]; then
    echo "⚠️  « $nom » : il faut ${besoin} Mo libres, tu en as ${libre}. Assemblage ignoré."
    echo "    Libère de la place, ou agrandis le disque Linux dans les Paramètres."
    continue
  fi
  echo "🔧 Assemblage de « $nom »…"
  echo "    image : $(du -h "$video" | cut -f1)   son : $(du -h "$audio" | cut -f1)"
  echo "    ⏳ environ $(( taille_mo / 200 + 1 )) min — NE PAS appuyer sur Ctrl+C."
  if ffmpeg -nostdin -loglevel warning -stats -y -i "$video" -i "$audio" \
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
    echo "    ❌ assemblage interrompu ou impossible."
    echo "       Les morceaux sont conservés : relance ./reparer.sh et laisse-le finir."
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
