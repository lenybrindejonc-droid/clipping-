#!/usr/bin/env python3
"""Programme une série de clips sur YouTube, étalée sur plusieurs jours.

Lit un dossier contenant les clips et le fichier textes.md produit par le site
(bouton « Tout télécharger »), puis planifie les publications.

Rien n'est envoyé sans ton accord : le plan complet s'affiche d'abord.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

RACINE = Path(__file__).resolve().parent
FUSEAU = ZoneInfo("Europe/Paris")
QUOTA_JOUR = 6          # limite gratuite de l'API YouTube
JOURS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def date_fr(d: datetime) -> str:
    return f"{JOURS[d.weekday()]} {d:%d/%m à %H:%M}"


def lire_textes(dossier: Path) -> dict[str, dict]:
    """Récupère le titre et la légende YouTube de chaque clip depuis textes.md."""
    fichier = dossier / "textes.md"
    if not fichier.exists():
        return {}
    clips: dict[str, dict] = {}
    courant: dict | None = None
    section = None
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("## "):
            titre = ligne[3:].split("—", 1)[-1].strip()
            courant = {"titre": titre, "description": ""}
            section = None
        elif courant is not None and ligne.startswith("Fichier : "):
            clips[ligne.split("Fichier : ", 1)[1].strip()] = courant
        elif ligne.startswith("Légende YouTube"):
            section = "description"
        elif ligne.startswith(("Légende ", "Accroches", "Durée", "##", "  [")):
            section = None
        elif courant is not None and section == "description" and ligne.strip():
            courant["description"] += ("\n" if courant["description"] else "") + ligne.strip()
    return clips


def plan(clips: list[Path], textes: dict, par_jour: int, heures: list[str],
         premier_jour: datetime) -> list[tuple[Path, str, str, datetime]]:
    """Associe à chaque clip son titre, sa description et sa date de publication."""
    programme = []
    for i, clip in enumerate(clips):
        jour = premier_jour + timedelta(days=i // par_jour)
        h, m = heures[i % par_jour].split(":")
        quand = jour.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        infos = textes.get(clip.name, {})
        titre = (infos.get("titre") or clip.stem)[:100]
        description = infos.get("description") or ""
        programme.append((clip, titre, description, quand))
    return programme


def main() -> None:
    p = argparse.ArgumentParser(description="Programme une série de clips sur YouTube.")
    p.add_argument("dossier", nargs="?", default=".", help="dossier contenant les clips")
    p.add_argument("--par-jour", type=int, default=3, help="clips publiés par jour (défaut : 3)")
    p.add_argument("--heures", default="12:30,18:30,21:00",
                   help="heures de publication, séparées par des virgules (heure de Paris)")
    p.add_argument("--a-partir-de", default="", help="premier jour, « AAAA-MM-JJ » (défaut : demain)")
    p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    args = p.parse_args()

    dossier = Path(args.dossier).expanduser().resolve()
    clips = sorted(f for f in dossier.glob("*.mp4") if not f.name.startswith("source"))
    if not clips:
        raise SystemExit(f"❌ Aucun clip (.mp4) dans {dossier}")

    heures = [h.strip() for h in args.heures.split(",") if h.strip()]
    par_jour = max(1, min(args.par_jour, len(heures)))
    if par_jour > QUOTA_JOUR:
        print(f"⚠️  YouTube n'autorise qu'environ {QUOTA_JOUR} envois par jour avec le quota gratuit.")

    if args.a_partir_de:
        premier = datetime.strptime(args.a_partir_de, "%Y-%m-%d").replace(tzinfo=FUSEAU)
    else:
        premier = datetime.now(FUSEAU) + timedelta(days=1)

    textes = lire_textes(dossier)
    programme = plan(clips, textes, par_jour, heures, premier)

    print(f"\n📅 Plan de publication — {len(clips)} clips, {par_jour} par jour\n")
    for clip, titre, description, quand in programme:
        print(f"  {date_fr(quand):<17} {clip.name:<16} {titre[:52]}")
        if not description:
            print(f"                   {'':16} ⚠️  pas de description trouvée dans textes.md")
    print(f"\n  Visibilité : {args.privacy} jusqu'à la date, puis publique automatiquement.")
    if not textes:
        print("  ⚠️  textes.md absent : les titres viennent des noms de fichiers.")

    reponse = input("\nLancer la programmation ? (oui/non) : ").strip().lower()
    if reponse not in ("oui", "o"):
        print("Annulé. Rien n'a été envoyé.")
        return

    for i, (clip, titre, description, quand) in enumerate(programme, 1):
        print(f"\n[{i}/{len(programme)}] {clip.name} → {date_fr(quand)}")
        commande = [sys.executable, str(RACINE / "youtube_upload.py"),
                    "--file", str(clip), "--title", titre, "--description", description,
                    "--publish-at", quand.strftime("%Y-%m-%d %H:%M")]
        if subprocess.run(commande).returncode != 0:
            print("\n❌ Arrêt : cet envoi a échoué. Les suivants n'ont pas été lancés.")
            print("   (quota journalier atteint ? autorisation expirée ?)")
            raise SystemExit(1)

    print("\n✅ Toute la série est programmée. Vérifie dans YouTube Studio.")


if __name__ == "__main__":
    main()
