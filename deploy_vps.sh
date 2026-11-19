#!/usr/bin/env bash
# Installe (ou met à jour) le site sur ton serveur VPS, en HTTPS, protégé par mot de passe.
# Usage : ./deploy_vps.sh
set -euo pipefail
cd "$(dirname "$0")"

CONF=.deploy_vps.conf
[ -f "$CONF" ] && . "$CONF"

command -v ssh >/dev/null || { echo "❌ ssh manquant. Lance : sudo apt install -y openssh-client"; exit 1; }

# ---------------------------------------------------------------- questions
read -rp "Adresse IP de ton serveur${SERVER_IP:+ [$SERVER_IP]} : " ip
ip=${ip:-${SERVER_IP:-}}
if ! [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  echo "❌ Ce n'est pas une adresse IP (exemple : 203.0.113.45)"; exit 1
fi
read -rp "Nom d'utilisateur du serveur${SERVER_USER:+ [$SERVER_USER]} [root] : " user
user=${user:-${SERVER_USER:-root}}

if [ ! -f .env ]; then echo "❌ Fichier .env introuvable. Lance d'abord ./install.sh"; exit 1; fi
set -a; . ./.env; set +a

[[ "${ANTHROPIC_API_KEY:-}" == sk-ant-* ]] || echo "⚠️  Pas de clé Claude : les moments seront choisis en mode basique."
[[ "${GROQ_API_KEY:-}" == gsk_* ]] || echo "⚠️  Pas de clé Groq : la transcription sera lente."

pass=${APP_PASSWORD:-}
if [ -z "$pass" ]; then
  echo
  echo "Ton site sera accessible depuis Internet : un mot de passe est obligatoire."
  read -rp "Choisis un mot de passe pour le site : " pass
  [ -n "$pass" ] || { echo "❌ Mot de passe vide."; exit 1; }
fi

site="${ip//./-}.sslip.io"   # nom de domaine gratuit basé sur l'IP → HTTPS automatique
printf 'SERVER_IP=%s\nSERVER_USER=%s\n' "$ip" "$user" > "$CONF"

# ---------------------------------------------------------------- connexion unique (un seul mot de passe à taper)
sock=$(mktemp -u /tmp/clipping-ssh-XXXX)
SSH=(ssh -o ControlMaster=auto -o "ControlPath=$sock" -o ControlPersist=10m -o StrictHostKeyChecking=accept-new)
cleanup() { ssh -o "ControlPath=$sock" -O exit "$user@$ip" 2>/dev/null || true; }
trap cleanup EXIT

echo
echo "🔌 Connexion à $user@$ip (tape le mot de passe du serveur si demandé)…"
"${SSH[@]}" "$user@$ip" "echo ok" >/dev/null

# ---------------------------------------------------------------- installation de Docker
echo "📦 Vérification de Docker sur le serveur…"
"${SSH[@]}" "$user@$ip" bash -s <<'REMOTE'
set -e
if ! command -v docker >/dev/null; then
  echo "   Installation de Docker (2-3 minutes)…"
  export DEBIAN_FRONTEND=noninteractive
  curl -fsSL https://get.docker.com | sh >/dev/null
fi
docker compose version >/dev/null 2>&1 || { echo "❌ docker compose manquant"; exit 1; }
mkdir -p /opt/clipping
REMOTE

# ---------------------------------------------------------------- envoi du code
echo "🚀 Envoi du code…"
tar czf - --exclude=__pycache__ app static requirements.txt Dockerfile docker-compose.yml Caddyfile \
  | "${SSH[@]}" "$user@$ip" "tar xzf - -C /opt/clipping"

# .env du serveur (clés + mot de passe), transmis par le tunnel chiffré, jamais affiché
{
  echo "SITE_ADDRESS=$site"
  echo "APP_PASSWORD=$pass"
  echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}"
  echo "GROQ_API_KEY=${GROQ_API_KEY:-}"
  echo "WHISPER_MODEL=${WHISPER_MODEL:-base}"
  if [ -n "${CLAUDE_MODEL:-}" ]; then echo "CLAUDE_MODEL=$CLAUDE_MODEL"; fi
  if [ -f cookies.txt ]; then
    # une seule ligne : les retours à la ligne deviennent \n (décodés côté serveur)
    echo "YT_COOKIES=$(awk '{printf "%s\\n", $0}' cookies.txt)"
  fi
  echo "WORKERS=1"
} | "${SSH[@]}" "$user@$ip" "cat > /opt/clipping/.env && chmod 600 /opt/clipping/.env"
if [ -f cookies.txt ]; then echo "🍪 Cookies YouTube envoyés."; fi

# ---------------------------------------------------------------- démarrage
echo "🏗️  Construction et démarrage (5-10 minutes la première fois)…"
"${SSH[@]}" "$user@$ip" "cd /opt/clipping && docker compose up -d --build"

echo
echo "✅ Terminé !"
echo "   Ton site : https://$site"
echo "   Mot de passe du site : celui que tu as choisi."
echo
echo "   Voir les journaux :  ssh $user@$ip 'cd /opt/clipping && docker compose logs -f app'"
echo "   Mettre à jour :      ./deploy_vps.sh"
