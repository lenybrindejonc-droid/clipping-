"""Mémoire des retours de l'utilisateur sur les clips.

Chaque avis est enregistré, puis résumé et transmis à l'IA avant le lot suivant :
elle apprend ainsi des erreurs constatées (début trop tôt, fin trop tardive, etc.).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

RAISONS = {
    "debut_tot": "le clip commence trop tôt (longueur inutile avant le moment fort)",
    "debut_tard": "le clip commence trop tard (on rate la mise en place)",
    "fin_tot": "le clip se termine trop tôt (le dénouement est coupé)",
    "fin_tard": "le clip traîne après le dénouement",
    "pas_interessant": "le passage n'a aucun intérêt",
    "hors_contexte": "le clip ne se comprend pas sans le reste de la vidéo",
    "accroche": "l'accroche ou le titre ne correspond pas au contenu",
}

FICHIER = Path(os.getenv("DATA_DIR", "data")) / "lessons.json"
_verrou = threading.Lock()
MAX_AVIS = 200


def _lire() -> list[dict]:
    try:
        return json.loads(FICHIER.read_text())
    except Exception:
        return []


def ajouter(verdict: str, raison: str = "", note: str = "", contexte: dict | None = None) -> int:
    """Enregistre un avis. Renvoie le nombre total d'avis."""
    with _verrou:
        avis = _lire()
        avis.append({
            "date": time.time(), "verdict": verdict,
            "raison": raison, "note": note.strip()[:200], **(contexte or {}),
        })
        avis = avis[-MAX_AVIS:]
        FICHIER.parent.mkdir(parents=True, exist_ok=True)
        FICHIER.write_text(json.dumps(avis, ensure_ascii=False, indent=1))
        return len(avis)


def resume(limite: int = 40) -> str:
    """Texte court à donner à l'IA avant de choisir le lot suivant."""
    avis = _lire()[-limite:]
    if len(avis) < 3:
        return ""   # trop peu de retours pour en tirer quoi que ce soit

    bons = sum(1 for a in avis if a["verdict"] == "bon")
    comptes: dict[str, int] = {}
    for a in avis:
        if a["verdict"] == "mauvais" and a.get("raison") in RAISONS:
            comptes[a["raison"]] = comptes.get(a["raison"], 0) + 1

    lignes = [f"Sur les {len(avis)} derniers clips notés, {bons} ont été jugés bons."]
    for raison, n in sorted(comptes.items(), key=lambda x: -x[1])[:4]:
        if n >= 2:
            lignes.append(f"- {n} fois : {RAISONS[raison]}. Corrige ce défaut.")
    notes = [a["note"] for a in avis if a.get("note")][-3:]
    for n in notes:
        lignes.append(f"- remarque de l'utilisateur : « {n} »")
    return "\n".join(lignes) if len(lignes) > 1 else ""
