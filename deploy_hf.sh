#!/usr/bin/env bash
# Met (ou remet à jour) le site en ligne sur Hugging Face, en privé.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then echo "Lance d'abord ./install.sh"; exit 1; fi
.venv/bin/pip install -q -U huggingface_hub
.venv/bin/python deploy_hf.py
