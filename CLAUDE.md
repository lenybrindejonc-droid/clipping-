# Clipping — mémoire du projet

Ce fichier existe pour qu'une nouvelle conversation reprenne le projet sans tout réexpliquer.
**Parle français, simplement : l'utilisateur n'est pas développeur.** Explique ce que font les
commandes avant de les donner, et évite le jargon.

## Ce que fait le projet

Un site qui transforme une vidéo longue en shorts verticaux 9:16 prêts pour TikTok.
Usage réel : clips de streams **GTA** (facecam + gameplay), pour des campagnes de clipping.

Chaîne de traitement (`app/`) :

| Étape | Fichier | Détail |
|---|---|---|
| Téléchargement | `pipeline.py` | yt-dlp dans un processus séparé, arrêté au-delà de 20 min |
| Transcription | `cloud_transcribe.py` | Groq (gratuit, rapide) ; repli Whisper local, très lent |
| Niveau sonore | `pipeline.py` → `energy_profile` | rires, cris : note E0–E9 par passage, donnée à l'IA |
| Action à l'image | `pipeline.py` → `motion_profile` | crashs, poursuites : note V0–V9, donnée à l'IA |
| Zoom | `pipeline.py` → `_zoom_filter` | zoompan sur le pic son+image, avant les sous-titres |
| Choix des moments | `highlights.py` | Claude ; consignes de `presets.py` ; repli heuristique sans clé |
| Spécialisation | `presets.py` | 7 types : critères, durées, cadrage, style de sous-titres |
| Cadrage 9:16 | `reframe.py` | facecam auto OU coin indiqué par l'utilisateur → écran partagé ; sinon suivi du visage ou fond flou |
| Sous-titres | `subtitles.py` | ASS, mot par mot, mot actif en jaune |
| Interface | `static/` | envoi par morceaux, éditeur de clip, notation, 3 accroches, légendes par plateforme |

Skills du compte utilisés comme référence : `choix-moments-clips-gta` (grille de sélection,
intégrée dans `presets.py`) et `gta6-clip-production` (3 accroches, légendes TikTok/YouTube/Reels,
vérification des règles de campagne). `youtube-upload-auto` → `youtube_upload.py` + `publier.sh` (publication **locale**, jamais
depuis le Space : le jeton YouTube ne doit pas être sur un serveur public).

## État au 22/11/2026

- **Hébergé sur Hugging Face Spaces** (PRO, ~9 $/mois), Space **public** + mot de passe
  (`APP_PASSWORD`), parce que les Spaces privés ne s'ouvrent pas depuis Safari iOS.
- Tout est prêt pour un **VPS auto-hébergé** (`deploy_vps.sh`, Docker Compose + Caddy,
  HTTPS gratuit via sslip.io). Moins cher, clips conservés, reste privé. Décision reportée.
- **Résultats (22/11)** : 1er lot = 5 clips, 3 très bons, 2 au cadrage raté (facecam non
  reconnue → cadrage « visage plein écran », corrigé depuis : seuils élargis + choix manuel
  du coin). 2e lot jugé **« très bien »** par l'utilisateur : la chaîne est validée.

## Pièges rencontrés (ne pas refaire le diagnostic)

1. **YouTube bloque les serveurs.** Depuis Hugging Face : connexion coupée (`SSL: UNEXPECTED_EOF`).
   Les cookies n'y changent rien, le blocage est antérieur à toute authentification.
   → L'utilisateur télécharge sur son Chromebook (`telecharger.sh`) puis envoie le fichier.
2. **YouTube bloque aussi par adresse IP** après plusieurs essais ratés. Ne jamais enchaîner
   les tentatives : `telecharger.sh` n'en fait que 2. Attendre un jour si ça bloque.
3. **Cookies YouTube** : à exporter en navigation privée, puis fermer la fenêtre sans se
   déconnecter, sinon ils sont invalidés. Les scripts trouvent le fichier quel que soit son nom.
4. **`yt-dlp` a besoin de deno + yt-dlp-ejs** (défis JavaScript), sinon « No video formats found ».
   Installés par `install_deno.sh` en local et directement dans le `Dockerfile` côté serveur.
5. **Téléchargement interrompu** = fichiers `.fNNN.mp4` + `.fNNN.m4a` + `.temp.mp4` inutilisable.
   `reparer.sh` assemble les morceaux sans rien retélécharger. Les envois ratés de l'utilisateur
   venaient de là : il envoyait des `.temp.mp4`.
6. **Envois coupés** : résolu par l'envoi en morceaux de 8 Mo avec reprise automatique.
7. **Hugging Face efface les fichiers** à chaque veille ou redémarrage : les clips et le fichier
   d'avis sont perdus. Toujours dire de télécharger les clips tout de suite. Conséquence :
   les notes 👍/👎 ne survivent pas à un redéploiement, donc tant qu'on est sur Hugging Face,
   mieux vaut que l'utilisateur dise ses retours en conversation (on les encode dans
   `presets.py`). Le VPS réglerait ça.
8. **Redéployer annule les vidéos en cours** — prévenir avant de proposer `deploy_hf.sh`.
9. **Confusion sources / clips** : `~/videos` contient les vidéos d'origine (streams de 30 min),
   pas les clips. Les clips se téléchargent depuis le site vers les Téléchargements ChromeOS.
   `youtube_upload.py` prévient si la vidéo dépasse 3 min ou n'est pas verticale.
10. **Emojis incrustés = noir et blanc** (libass ne rend pas les emojis en couleur). Sans
   importance : l'utilisateur écrit ses accroches lui-même sur TikTok, où elles s'affichent
   en couleur. Les emojis sont donc demandés dans le texte, pas dans l'incrustation.

## Son matériel et ses habitudes

- **Chromebook** (Linux/penguin), Celeron N4020, 2 cœurs : très lent pour l'encodage.
  Disque Linux petit, souvent plein ; vérifier avec `df -h ~`.
- **iPhone** pour récupérer les clips et publier.
- Réponses courtes, souvent sans détail. **Poser une question précise à la fois**, ou proposer
  une commande unique de diagnostic (`diagnostic.sh`) plutôt que plusieurs allers-retours.

## Scripts (tous à la racine, lancés depuis `~/clipping-`)

```bash
./install.sh                      # installation complète (environnement Python, ffmpeg, deno)
./start.sh                        # site en local sur http://localhost:8000
./telecharger.sh "LIEN"           # télécharge une vidéo ; QUALITE=720 pour un fichier léger
./reparer.sh                      # assemble les téléchargements interrompus
./decouper.sh [fichier] [minutes] # découpe une vidéo longue en parties
./diagnostic.sh "LIEN"            # bilan complet quand YouTube refuse
./deploy_hf.sh                    # met à jour le site sur Hugging Face
./deploy_vps.sh                   # déploie sur un serveur auto-hébergé
./publier.sh "clip.mp4" "Titre"   # publie sur YouTube (aperçu + confirmation obligatoires)
./programmer.sh dossier           # programme une série de clips, étalée sur plusieurs jours
```

## Clés et réglages (`.env`, jamais dans git)

`ANTHROPIC_API_KEY` (choix des moments, ~5–10 centimes par vidéo) ·
`GROQ_API_KEY` (transcription, gratuit) · `APP_PASSWORD` · `WHISPER_MODEL` ·
`CLAUDE_MODEL` · `QUALITE` · `MAX_UPLOAD_GB`.

## Règles de travail sur ce projet

- **Tester avant d'affirmer.** Playwright pour l'interface, ffmpeg pour le rendu. Dire clairement
  ce qui n'a pas pu être testé ici : YouTube, Groq, l'API Claude et les dépôts Debian sont
  inaccessibles depuis l'environnement de développement.
- **Ne jamais proposer de contourner les protections** d'une plateforme. Pour les campagnes,
  la bonne source reste les fichiers fournis par le créateur.
- Commits en français, poussés sur la branche de travail. Ne pas créer de pull request
  sans demande explicite.
- `lessons.json` (avis sur les clips) est relu par `highlights.py` à chaque analyse :
  c'est la boucle d'amélioration, ne pas la casser.

## Pistes non faites

1. Suivi de la personne qui parle (podcasts à plusieurs).
   (Rien de réutilisable trouvé sur GitHub ni pour les critères par type, ni pour l'écriture
   des accroches : `presets.py` est maison.)
2. Musique de fond libre de droits, publication directe TikTok.
3. YouTube : projet Google en mode **Test** (la production exige site web + page de
   confidentialité) → autorisation renouvelée tous les 7 jours, automatiquement par le script.
   Quota ~6 envois/jour ; vidéos forcées en privé tant que le projet n'a pas passé l'audit.
   `client_secret.json` et `token.json` sont dans `.gitignore`.
