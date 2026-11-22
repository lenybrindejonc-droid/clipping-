#!/usr/bin/env python3
"""Envoie une vidéo sur la chaîne YouTube de l'utilisateur (API YouTube Data v3).

Rien n'est publié sans que tu lances la commande toi-même. Utilise d'abord --dry-run
pour voir le résumé, puis relance sans --dry-run.

Les fichiers client_secret.json et token.json restent sur cette machine : ne les partage
jamais, et ne les envoie nulle part.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
RACINE = Path(__file__).resolve().parent
SECRET = RACINE / "client_secret.json"
JETON = RACINE / "token.json"
FUSEAU = ZoneInfo("Europe/Paris")
CATEGORIES = {"jeux": "20", "gaming": "20", "voyage": "19", "divertissement": "24"}
RETRIABLES = (500, 502, 503, 504)


def quand(texte: str) -> str:
    """« 2026-11-25 18:30 » (heure de Paris) → format attendu par YouTube (UTC)."""
    local = datetime.strptime(texte.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=FUSEAU)
    if local <= datetime.now(FUSEAU):
        raise SystemExit("❌ La date de publication doit être dans le futur.")
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def identifiants():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = Credentials.from_authorized_user_file(str(JETON), SCOPES) if JETON.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not SECRET.exists():
            raise SystemExit(
                f"❌ Fichier manquant : {SECRET.name}\n"
                "   Crée-le dans Google Cloud (identifiant OAuth « Application de bureau »),\n"
                "   puis dépose-le dans le dossier clipping-. Voir README, section YouTube."
            )
        print("🔐 Une page Google va s'ouvrir pour autoriser ta chaîne…")
        creds = InstalledAppFlow.from_client_secrets_file(str(SECRET), SCOPES).run_local_server(port=0)
    JETON.write_text(creds.to_json())
    JETON.chmod(0o600)
    return creds


def envoyer(args) -> None:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    corps = {
        "snippet": {
            "title": args.title[:100],
            "description": args.description,
            "tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()][:15],
            "categoryId": CATEGORIES.get((args.category or "jeux").lower(), args.category or "20"),
        },
        "status": {
            "privacyStatus": args.privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    if args.publish_at:
        corps["status"]["publishAt"] = quand(args.publish_at)
        corps["status"]["privacyStatus"] = "private"   # obligatoire pour une publication programmée

    taille = Path(args.file).stat().st_size / 1048576
    print("────────── Résumé ──────────")
    print(f"Fichier     : {args.file}  ({taille:.0f} Mo)")
    print(f"Titre       : {corps['snippet']['title']}")
    print(f"Description : {corps['snippet']['description'][:90]}{'…' if len(corps['snippet']['description']) > 90 else ''}")
    print(f"Tags        : {', '.join(corps['snippet']['tags']) or '(aucun)'}")
    print(f"Visibilité  : {corps['status']['privacyStatus']}"
          + (f" puis publique le {args.publish_at} (heure de Paris)" if args.publish_at else ""))
    if args.thumbnail:
        print(f"Miniature   : {args.thumbnail}")
    print("────────────────────────────")

    if args.dry_run:
        print("🧪 --dry-run : rien n'a été envoyé. Relance sans --dry-run pour publier.")
        return

    service = build("youtube", "v3", credentials=identifiants(), cache_discovery=False)
    media = MediaFileUpload(args.file, chunksize=8 * 1024 * 1024, resumable=True,
                            mimetype="video/*")
    requete = service.videos().insert(part="snippet,status", body=corps, media_body=media)

    reponse, essai = None, 0
    while reponse is None:
        try:
            progression, reponse = requete.next_chunk()
            if progression:
                print(f"\r⬆️  Envoi… {int(progression.progress() * 100)} %", end="", flush=True)
        except HttpError as exc:
            if exc.resp.status in RETRIABLES and essai < 5:
                essai += 1
                attente = 2 ** essai
                print(f"\n⚠️  Erreur {exc.resp.status}, nouvel essai dans {attente} s…")
                time.sleep(attente)
            else:
                raise SystemExit(f"\n❌ Envoi refusé par YouTube : {exc}")
    print()

    vid = reponse["id"]
    print(f"✅ Publié : https://youtu.be/{vid}")
    print(f"   Statut : {reponse['status']['privacyStatus']}")

    if args.thumbnail and Path(args.thumbnail).exists():
        try:
            service.thumbnails().set(videoId=vid, media_body=MediaFileUpload(args.thumbnail)).execute()
            print("   Miniature envoyée.")
        except Exception as exc:
            print(f"   ⚠️ Miniature refusée ({exc}). La vidéo est publiée quand même.")

    print("\nℹ️  Tant que ton projet Google Cloud n'a pas passé l'audit de YouTube, les vidéos")
    print("   envoyées par l'API restent PRIVÉES, même si tu demandes « public ».")
    print("   Dans ce cas, rends-les publiques à la main dans YouTube Studio.")


def main() -> None:
    p = argparse.ArgumentParser(description="Publie un Short sur ta chaîne YouTube.")
    p.add_argument("--file", required=True, help="la vidéo à envoyer")
    p.add_argument("--title", required=True, help="titre, 100 caractères maximum")
    p.add_argument("--description", default="", help="description de la vidéo")
    p.add_argument("--tags", default="", help="mots-clés séparés par des virgules")
    p.add_argument("--category", default="jeux", help="jeux (20), voyage (19), divertissement (24)")
    p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"],
                   help="visibilité (par défaut : privée)")
    p.add_argument("--publish-at", default="", help="programmer : « 2026-11-25 18:30 » (heure de Paris)")
    p.add_argument("--thumbnail", default="", help="image de miniature (facultatif)")
    p.add_argument("--dry-run", action="store_true", help="afficher le résumé sans rien envoyer")
    args = p.parse_args()

    if not Path(args.file).exists():
        raise SystemExit(f"❌ Vidéo introuvable : {args.file}")
    if not args.title.strip():
        raise SystemExit("❌ Le titre est obligatoire.")
    envoyer(args)


if __name__ == "__main__":
    sys.exit(main())
