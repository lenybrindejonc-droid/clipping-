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


def reglages_env() -> dict[str, str]:
    env = {}
    fichier = RACINE / ".env"
    if fichier.exists():
        for ligne in fichier.read_text().splitlines():
            if "=" in ligne and not ligne.lstrip().startswith("#"):
                cle, valeur = ligne.split("=", 1)
                env[cle.strip()] = valeur.strip().strip('"').strip("'")
    return env


def _adresse_propre(adresse: str) -> str:
    """Accepte « leno10-clipping.hf.space » aussi bien que l'adresse complète."""
    adresse = adresse.strip().rstrip("/")
    if not adresse:
        raise SystemExit("❌ Aucune adresse de site. Relance ./deploy_hf.sh ou utilise --site.")
    if not adresse.startswith(("http://", "https://")):
        adresse = "https://" + adresse
    return adresse


def recuperer_du_site(adresse: str, mot_de_passe: str, destination: Path,
                      bibliotheque: bool = False) -> Path:
    """Télécharge les clips du dernier projet terminé, directement depuis le site."""
    import io
    import zipfile

    import httpx

    adresse = _adresse_propre(adresse)
    print(f"🔗 Connexion à {adresse}")
    try:
        return _recuperer(adresse, mot_de_passe, destination, bibliotheque)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        explications = {
            401: "mot de passe du site refusé.",
            403: "accès refusé par le site.",
            404: "page introuvable : le site répond, mais pas l'application.\n"
                 "   Ton Space est peut-être encore privé, ou l'adresse pointe ailleurs.",
            503: "le site est en train de démarrer (mise en veille).\n"
                 "   Ouvre-le dans ton navigateur, attends qu'il affiche la page, puis relance.",
            500: "erreur interne du site : regarde les journaux du Space.",
        }
        raise SystemExit(
            f"❌ Le site a répondu {code} — {explications.get(code, 'réponse inattendue.')}\n"
            f"   Adresse essayée : {adresse}\n"
            f"   Ouvre-la dans ton navigateur pour vérifier qu'elle fonctionne."
        ) from None
    except httpx.HTTPError as exc:
        raise SystemExit(
            f"❌ Impossible de joindre {adresse} ({exc.__class__.__name__}).\n"
            "   Vérifie l'orthographe de l'adresse (exemple : leno10-clipping.hf.space)\n"
            "   et que le site s'ouvre bien dans ton navigateur.\n"
            "   Adresse actuellement enregistrée :  grep SITE_URL .env\n"
            "   Pour en donner une autre :  ./programmer.sh --site TON_ADRESSE"
        ) from None


def _recuperer(adresse: str, mot_de_passe: str, destination: Path, bibliotheque: bool) -> Path:
    import httpx

    with httpx.Client(base_url=adresse, timeout=600, follow_redirects=True) as client:
        if mot_de_passe:
            client.post("/login", data={"password": mot_de_passe})
        if bibliotheque:
            archive = client.get("/api/library/zip")
            if archive.status_code == 401:
                raise SystemExit("❌ Mot de passe du site refusé.")
            if archive.status_code == 404:
                raise SystemExit("❌ Aucun clip à publier dans la bibliothèque.")
            archive.raise_for_status()
            print("\n⬇️  Récupération de la bibliothèque…")
            return _extraire(archive.content, destination)

        reponse = client.get("/api/jobs")
        if reponse.status_code == 401:
            raise SystemExit("❌ Mot de passe du site refusé.")
        reponse.raise_for_status()
        projets = [p for p in reponse.json() if p.get("status") == "done" and p.get("clips")]
        if not projets:
            raise SystemExit("❌ Aucun projet terminé sur le site.")

        if len(projets) > 1:
            print("\nProjets disponibles :")
            for i, p in enumerate(projets, 1):
                print(f"  {i}. {p.get('title') or p['id']}  ({len(p['clips'])} clips)")
            choix = input(f"Lequel ? (1-{len(projets)}, Entrée = 1) : ").strip() or "1"
            projet = projets[int(choix) - 1] if choix.isdigit() and 1 <= int(choix) <= len(projets) else projets[0]
        else:
            projet = projets[0]

        print(f"\n⬇️  Récupération de « {projet.get('title') or projet['id']} » "
              f"({len(projet['clips'])} clips)…")
        archive = client.get(f"/api/jobs/{projet['id']}/zip")
        archive.raise_for_status()

    return _extraire(archive.content, destination)


def _extraire(contenu: bytes, destination: Path) -> Path:
    import io
    import zipfile

    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(contenu)) as z:
        z.extractall(destination)
    print(f"   {len(list(destination.glob('*.mp4')))} clips enregistrés dans {destination}")
    return destination


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
        elif courant is not None and ligne.startswith("Source : "):
            courant["source"] = ligne[len("Source : "):].split(" · ", 1)[0].strip()
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
    occupation: dict[int, list[str]] = {}       # jour → sources déjà publiées ce jour-là
    for clip in clips:
        infos = textes.get(clip.name, {})
        source = infos.get("source") or "?"
        # Jamais 2 clips de la même vidéo source le même jour : TikTok et YouTube les
        # voient comme du contenu répété, et ils se font concurrence.
        d = 0
        while len(occupation.get(d, [])) >= par_jour or source in occupation.get(d, []):
            d += 1
        occupation.setdefault(d, []).append(source)
        h, m = heures[len(occupation[d]) - 1].split(":")
        quand = (premier_jour + timedelta(days=d)).replace(hour=int(h), minute=int(m),
                                                           second=0, microsecond=0)
        titre = (infos.get("titre") or clip.stem)[:100]
        description = infos.get("description") or ""
        programme.append((clip, titre, description, quand))
    return sorted(programme, key=lambda x: x[3])


def main() -> None:
    p = argparse.ArgumentParser(description="Programme une série de clips sur YouTube.")
    p.add_argument("dossier", nargs="?", default="",
                   help="dossier contenant les clips ; vide = récupérer depuis le site")
    p.add_argument("--site", default="", help="adresse du site (sinon SITE_URL du fichier .env)")
    p.add_argument("--bibliotheque", action="store_true",
                   help="prendre les clips de la bibliothèque plutôt qu'un projet")
    p.add_argument("--par-jour", type=int, default=3, help="clips publiés par jour, toutes sources confondues (défaut : 3) ; "
                        "jamais plus d'1 par vidéo source")
    p.add_argument("--heures", default="12:30,18:30,21:00",
                   help="heures de publication, séparées par des virgules (heure de Paris)")
    p.add_argument("--a-partir-de", default="", help="premier jour, « AAAA-MM-JJ » (défaut : demain)")
    p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    args = p.parse_args()

    if args.dossier:
        dossier = Path(args.dossier).expanduser().resolve()
    else:
        env = reglages_env()
        adresse = args.site or env.get("SITE_URL", "")
        if not adresse:
            adresse = input("Adresse de ton site (ex. https://leno10-clipping.hf.space) : ").strip()
        mot_de_passe = env.get("APP_PASSWORD", "")
        if not mot_de_passe:
            mot_de_passe = input("Mot de passe du site (Entrée si aucun) : ").strip()
        dossier = recuperer_du_site(adresse, mot_de_passe, RACINE.parent / "clips_du_site",
                                    bibliotheque=args.bibliotheque)
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
