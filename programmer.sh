#!/usr/bin/env bash
# Programme une série de clips sur YouTube, étalée sur plusieurs jours.
# Usage : ./programmer.sh ~/Téléchargements/mon_dossier_de_clips [options]
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then echo "Lance d'abord ./install.sh"; exit 1; fi
.venv/bin/pip install -q google-api-python-client google-auth-oauthlib >/dev/null 2>&1 || true
exec .venv/bin/python programmer.py "$@"
