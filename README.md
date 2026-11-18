# ✂️ Clipping — YouTube → shorts viraux

Colle un lien YouTube : le site télécharge la vidéo, la transcrit, demande à Claude de repérer
les meilleurs moments, puis monte automatiquement des shorts verticaux (9:16) avec sous-titres
animés, prêts pour TikTok, Reels et YouTube Shorts.

## Comment ça marche

| Étape | Outil | Détail |
|---|---|---|
| 1. Téléchargement | `yt-dlp` | vidéo ≤ 1080p en mp4 |
| 2. Transcription | `faster-whisper` (local) | horodatage au mot près, détection de langue |
| 3. Choix des moments | Claude (`claude-opus-5-5`) | hook fort, clip autonome, payoff, fin propre ; renvoie titre, accroche, légende, hashtags, score de viralité |
| 4. Recadrage 9:16 | OpenCV + ffmpeg | suit le visage principal (plans fixes + glissements rapides), ou vidéo entière sur fond flou |
| 5. Sous-titres | ASS + libass | style TikTok : 3 mots par ligne, mot prononcé en jaune, bandeau d'accroche en haut |

Sans clé API, une sélection heuristique de secours est utilisée (densité de parole + mots d'accroche) — ça marche, mais c'est nettement moins bon.

## Lancer en local

Prérequis : Python 3.10+ et `ffmpeg`.

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # optionnel mais recommandé
uvicorn app.main:app --port 8000
```

Puis ouvre http://localhost:8000.

### Avec Docker

```bash
docker build -t clipping .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... -v $(pwd)/data:/srv/data clipping
```

## Réglages (variables d'environnement)

Voir `.env.example` : `WHISPER_MODEL` (`small` par défaut ; `medium`/`large-v3` plus précis sur GPU),
`SUBTITLE_FONT`, `KEEP_SOURCE`, `WORKERS` (vidéos traitées en parallèle), `DATA_DIR`, `CLAUDE_MODEL`.

## Structure

```
app/main.py        API FastAPI + file de traitement
app/pipeline.py    téléchargement, transcription, rendu ffmpeg
app/highlights.py  sélection des moments (Claude + repli heuristique)
app/reframe.py     recadrage automatique sur le visage
app/subtitles.py   sous-titres animés
static/            interface web
```

## Pistes pour la suite

- Détection du locuteur actif (lèvres/audio) pour les podcasts à plusieurs.
- Éditeur pour ajuster début/fin d'un clip avant export.
- Publication directe via les API TikTok / YouTube.
- Comptes utilisateurs + file de tâches (Redis/Celery) pour un déploiement public.
