"""Analyse approfondie de la transcription avant d'en faire des sous-titres.

Objectif : ne jamais afficher un texte absurde (« DU QUI JET », « MAKE. »).
1. Noms corrigés (corrections.json : Michou, Gotaga, GTA 6… + streamer et jeu saisis).
2. Phrases fantômes retirées : Whisper invente « Sous-titrage ST' 501 », « Merci d'avoir
   regardé »… pendant la musique ou les silences.
3. Boucles retirées : le même mot répété 4 fois ou plus est une erreur de transcription.
4. Chaque mot garde une note de confiance « p » (0 à 1) : subtitles.py masque les mots
   et les passages trop incertains, et coupe les sous-titres d'un clip entièrement douteux.
"""
from __future__ import annotations

import re

from . import corrections

FANTOMES = re.compile(
    r"(sous[- ]titr\w*|amara\.org|merci d'avoir regardé|abonnez[- ]vous|"
    r"n'oubliez pas de (vous abonner|liker)|thanks for watching|subtitles by|"
    r"st'? ?501|radio[- ]canada|♪)", re.I)


def _boucles(mots: list[dict]) -> list[dict]:
    """Retire les répétitions anormales (« on on on on on »)."""
    sortie: list[dict] = []
    for m in mots:
        meme = [x for x in sortie[-3:] if corrections._norm(x["word"]) == corrections._norm(m["word"])]
        if len(meme) >= 3:
            continue
        sortie.append(m)
    return sortie


def analyser(tr: dict, noms: list[str] | None = None) -> dict:
    """Nettoie la transcription sur place et la renvoie ; ajoute un résumé dans tr["analyse"]."""
    table = corrections.dictionnaire(noms)
    retires = corriges = 0
    segments = []
    for s in tr.get("segments", []):
        if FANTOMES.search(s.get("text", "")):
            retires += 1
            continue
        avant = [m["word"] for m in s.get("words", [])]
        mots = _boucles(corrections.corriger_mots(s.get("words", []), table))
        noms_justes = set(table.values())
        corriges += sum(1 for m in mots if m["word"] not in avant
                        and m["word"].rstrip(".,!?…") in noms_justes)
        s["words"] = mots
        if mots:
            s["text"] = " ".join(m["word"] for m in mots)
        segments.append(s)
    tr["segments"] = segments
    tr["analyse"] = {"phrases_fantomes_retirees": retires, "noms_corriges": corriges}
    return tr
