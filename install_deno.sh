#!/usr/bin/env bash
# Installe « deno », le moteur JavaScript que YouTube exige désormais pour yt-dlp.
set -e
DEST="${1:-$HOME/.local/bin}"
if command -v deno >/dev/null 2>&1; then echo "deno déjà installé"; exit 0; fi
case "$(uname -m)" in
  x86_64)  ASSET=deno-x86_64-unknown-linux-gnu.zip ;;
  aarch64) ASSET=deno-aarch64-unknown-linux-gnu.zip ;;
  *) echo "⚠️  Architecture non gérée ($(uname -m)) : deno non installé"; exit 0 ;;
esac
command -v unzip >/dev/null || sudo apt-get install -y unzip
mkdir -p "$DEST"
tmp=$(mktemp -d)
curl -fsSL -o "$tmp/deno.zip" "https://github.com/denoland/deno/releases/latest/download/$ASSET"
unzip -oq "$tmp/deno.zip" -d "$DEST"
chmod +x "$DEST/deno"
rm -rf "$tmp"
echo "✅ deno installé dans $DEST"
