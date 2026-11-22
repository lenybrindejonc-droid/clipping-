#!/usr/bin/env bash
# Publie un clip sur ta chaîne YouTube.
# Usage : ./publier.sh "~/Téléchargements/mon_clip.mp4" "Mon titre" ["description"]
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then echo "Lance d'abord ./install.sh"; exit 1; fi
if [ -z "${2:-}" ]; then
  echo 'Usage : ./publier.sh "fichier.mp4" "Titre du short" ["description"]'
  echo
  echo "Options utiles, à ajouter à la fin :"
  echo "  --privacy public            publier tout de suite (par défaut : privé)"
  echo '  --publish-at "2026-11-25 18:30"   programmer (heure de Paris)'
  echo "  --tags gta6,gaming          mots-clés"
  exit 1
fi
.venv/bin/pip install -q google-api-python-client google-auth-oauthlib >/dev/null 2>&1 || true

FICHIER="$1"; TITRE="$2"; DESC="${3:-}"
shift 2; [ $# -gt 0 ] && shift || true   # le reste part en options

echo "🧪 Aperçu (rien n'est envoyé) :"
.venv/bin/python youtube_upload.py --file "$FICHIER" --title "$TITRE" --description "$DESC" --dry-run "$@"
echo
read -rp "Publier pour de vrai ? (oui/non) : " reponse
if [ "$reponse" = "oui" ] || [ "$reponse" = "o" ]; then
  .venv/bin/python youtube_upload.py --file "$FICHIER" --title "$TITRE" --description "$DESC" "$@"
else
  echo "Annulé. Rien n'a été envoyé."
fi
