FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-dejavu-core fonts-liberation2 \
 && (apt-get install -y --no-install-recommends fonts-inter || echo "police Inter absente : police par défaut") \
 && fc-cache -f \
 && rm -rf /var/lib/apt/lists/*

# deno : moteur JavaScript désormais exigé par YouTube pour yt-dlp (sans lui, formats manquants).
# Installé directement ici (pas de COPY) pour que le build fonctionne quel que soit le mode d'envoi.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip ca-certificates \
 && case "$(uname -m)" in \
      x86_64)  DENO_ASSET=deno-x86_64-unknown-linux-gnu.zip ;; \
      aarch64) DENO_ASSET=deno-aarch64-unknown-linux-gnu.zip ;; \
      *)       DENO_ASSET="" ;; \
    esac \
 && if [ -n "$DENO_ASSET" ]; then \
      { curl -fsSL -o /tmp/deno.zip "https://github.com/denoland/deno/releases/latest/download/$DENO_ASSET" \
        && unzip -oq /tmp/deno.zip -d /usr/local/bin \
        && chmod +x /usr/local/bin/deno \
        && rm -f /tmp/deno.zip \
        && deno --version; } \
      || echo "deno non installé (téléchargement impossible) — le site fonctionne quand même"; \
    else echo "architecture non gérée : deno non installé"; fi \
 && apt-get purge -y unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Hugging Face lance le conteneur avec l'utilisateur 1000
RUN useradd -m -u 1000 user && mkdir -p /srv/data && chown -R user /srv
WORKDIR /srv
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=user app app
COPY --chown=user static static
USER user
ENV DATA_DIR=/srv/data HOME=/home/user PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
