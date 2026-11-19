FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-dejavu-core fonts-liberation2 \
 && (apt-get install -y --no-install-recommends fonts-inter || echo "police Inter absente : police par défaut") \
 && fc-cache -f \
 && rm -rf /var/lib/apt/lists/*
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
