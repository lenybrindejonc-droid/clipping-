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

## Publier sur YouTube

Publication depuis ton ordinateur (pas depuis le site : un jeton d'accès à la chaîne n'a
rien à faire sur un serveur public).

### Préparation, une seule fois

1. Crée un projet sur https://console.cloud.google.com et active **YouTube Data API v3**.
2. Écran de consentement OAuth : type **Externe**, ajoute ton adresse Gmail en
   **utilisateur test**. Reste en mode **Test** : passer en production exige un site web et
   une page de confidentialité. En mode Test, Google invalide l'autorisation tous les 7 jours,
   et le script la renouvelle tout seul (une page Google s'ouvre, tu cliques, c'est reparti).
3. Identifiants → **ID client OAuth** → type **Application de bureau** → télécharge le fichier
   et renomme-le `client_secret.json`, à déposer dans le dossier `clipping-`.

`client_secret.json` et `token.json` sont ignorés par git : ils restent sur ta machine.

### Programmer une série de clips

```bash
./programmer.sh --par-jour 3                    # va chercher les clips sur le site
./programmer.sh ~/Téléchargements/mes_clips     # ou depuis un dossier local
```

Sans dossier, le script se connecte au site (adresse et mot de passe lus dans `.env`,
renseignés automatiquement par `deploy_hf.sh`), propose les projets terminés et télécharge
celui que tu choisis. Il lit les clips et le `textes.md` fourni par le site,
puis affiche le plan complet (date et heure de chaque publication) avant de demander
confirmation. Options : `--heures "12:30,18:30,21:00"`, `--a-partir-de 2026-11-25`.

### Publier un clip

```bash
./publier.sh "~/Téléchargements/mon_clip.mp4" "GTA 6 : la poursuite finit mal" "Extrait du live. #Shorts #GTA6"
```

Le script affiche d'abord un aperçu et demande confirmation. Options utiles :

```bash
--privacy public                      # publier tout de suite (par défaut : privé)
--publish-at "2026-11-25 18:30"       # programmer (heure de Paris)
--tags gta6,gaming
```

**Deux limites de YouTube :** environ **6 envois par jour** avec le quota gratuit, et tant que
ton projet Google n'a pas passé l'audit YouTube, les vidéos envoyées par l'API **restent
privées** — à rendre publiques à la main dans YouTube Studio.

## Bibliothèque

Chaque clip monté est automatiquement rangé dans une bibliothèque (onglet 📚 de la page) et
conservé **30 jours**, même si le projet est supprimé. Aucun clic nécessaire. Un lien matériel
est utilisé, donc aucun espace disque supplémentaire n'est occupé. Durée réglable avec
`GARDE_JOURS` dans `.env`.

⚠️ Sur Hugging Face, les fichiers sont effacés à chaque mise en veille : la bibliothèque n'y
survit pas. Elle ne tient ses 30 jours qu'avec un stockage persistant (option payante de
Hugging Face) ou sur un serveur auto-hébergé.

## Apprentissage des retours

Chaque clip peut être noté sur la page (👍 / 👎 avec la raison). Les avis sont enregistrés
dans `data/lessons.json` et résumés dans les consignes données à l'IA au lot suivant
(à partir de 3 avis). Sur Hugging Face, ce fichier est effacé au redémarrage du Space ;
sur un serveur auto-hébergé il est conservé.

## Réglages (variables d'environnement)

Voir `.env.example` : `WHISPER_MODEL` (`base` par défaut (rapide) ; `small`, `medium`, `large-v3` plus précis mais plus lents),
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
- ~~Éditeur pour ajuster début/fin d'un clip~~ ✅ fait (bouton « Modifier » sur chaque clip).
- Publication directe via les API TikTok / YouTube.
- Comptes utilisateurs + file de tâches (Redis/Celery) pour un déploiement public.

## Mettre en ligne sur un serveur VPS (recommandé)

Un serveur à ~4-6 €/mois (Hetzner, OVH, Scaleway…) : 3 à 5× plus rapide que la plupart des
petits PC, clips conservés, site accessible depuis le téléphone.

1. Crée un serveur (2 vCPU / 4 Go, Ubuntu 24.04) et note son adresse IP.
2. Depuis le projet :

```bash
./deploy_vps.sh
```

Le script installe Docker sur le serveur, y copie le code, écrit le `.env` (clés + mot de passe
du site) et démarre le tout derrière **Caddy**, qui obtient un certificat HTTPS gratuit pour
`<ton-ip>.sslip.io` — aucun nom de domaine à acheter. Relance la même commande pour mettre à jour.

Le site est protégé par le mot de passe demandé lors du déploiement (`APP_PASSWORD`).

## Mettre en ligne sur Hugging Face (privé — abonnement PRO requis)

⚠️ Depuis 2026, Hugging Face réserve les Docker Spaces aux comptes PRO (~9 $/mois) ;
les Spaces gratuits n'acceptent que des pages statiques.

```bash
./deploy_hf.sh
```

Le script demande un token Hugging Face (https://huggingface.co/settings/tokens, type « Write »),
crée un Space **privé**, copie tes clés Claude/Groq du fichier `.env` dans les **Secrets** du Space
(jamais dans le code), propose un mot de passe pour le site, puis envoie le code.
Relance la même commande pour mettre le site à jour.

### Téléchargement interrompu

yt-dlp récupère l'image et le son séparément, puis les assemble. Si le téléchargement
s'arrête avant cette fusion, il reste des fichiers `.fNNN.mp4`, `.fNNN.m4a` et `.temp.mp4`,
tous inutilisables tels quels :

```bash
./reparer.sh     # assemble les morceaux complets, sans rien retélécharger
```

### Vidéos longues (plus de 1 h)

Un envoi de plusieurs Go échoue souvent (il suffit d'une coupure). Deux parades :

```bash
QUALITE=720 ./telecharger.sh "lien"      # fichier 2 à 3 fois plus léger
./decouper.sh ~/videos/ma_video.mp4 30   # découpe en parties de 30 min, sans ré-encoder
```

Chaque partie s'envoie séparément et donne ses propres clips.

### Envoyer une vidéo depuis son ordinateur

Si YouTube refuse le téléchargement depuis le serveur, utilise le bouton
**« Choisir une vidéo sur mon ordinateur »** sur la page : télécharge la vidéo là où ça marche
(ton PC), puis envoie le fichier au site. Formats acceptés : mp4, mkv, webm, mov, m4v, avi.

### YouTube bloque (« Sign in to confirm you're not a bot »)

YouTube bloque souvent les serveurs. Solution : des cookies d'un compte YouTube **secondaire**.
1. Dans Chrome, connecte-toi à YouTube avec ce compte et installe l'extension
   « Get cookies.txt LOCALLY ».
2. Sur youtube.com, exporte les cookies et enregistre le fichier sous `cookies.txt`
   dans le dossier du projet.
3. Relance `./deploy_hf.sh` : les cookies sont envoyés comme secret (jamais publiés).
