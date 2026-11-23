"""Corrige les noms que la transcription entend mal (Michou, Gotaga, GTA 6…).

Le dictionnaire est dans corrections.json : à gauche le nom correct, à droite les façons
dont la transcription l'écrit. Le nom du streamer et du jeu saisis sur le site s'y ajoutent.
Un nom en plusieurs morceaux (« gta » + « six ») devient un seul mot affiché « GTA 6 »,
avec l'horodatage du premier morceau au dernier.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

FICHIER = Path(__file__).with_name("corrections.json")
FENETRE = 3   # un nom mal entendu tient en 3 morceaux au plus


def _norm(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte.lower())
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", texte).strip()


def dictionnaire(noms: list[str] | None = None) -> dict[str, str]:
    """{forme mal entendue normalisée → forme correcte}."""
    try:
        brut = json.loads(FICHIER.read_text(encoding="utf-8"))
    except Exception:
        brut = {}
    table: dict[str, str] = {}
    for correct, variantes in brut.items():
        if correct.startswith("_"):
            continue
        for v in [correct, *variantes]:
            for forme in {_norm(v), _norm(v).replace(" ", "")}:
                if forme:
                    table[forme] = correct
    for nom in noms or []:
        nom = nom.strip()
        if nom:
            table.setdefault(_norm(nom), nom)
            table.setdefault(_norm(nom).replace(" ", ""), nom)
    return table


def mots_cles(noms: list[str] | None = None) -> str:
    """Les noms à souffler à Whisper pour qu'il les reconnaisse du premier coup."""
    try:
        brut = json.loads(FICHIER.read_text(encoding="utf-8"))
    except Exception:
        brut = {}
    liste = [n for n in brut if not n.startswith("_")] + [n.strip() for n in noms or [] if n.strip()]
    return ", ".join(dict.fromkeys(liste))


def corriger_mots(mots: list[dict], table: dict[str, str]) -> list[dict]:
    """Remplace les formes mal entendues, en fusionnant les morceaux d'un même nom."""
    sortie: list[dict] = []
    i = 0
    while i < len(mots):
        trouve = None
        for n in range(min(FENETRE, len(mots) - i), 0, -1):
            bloc = mots[i:i + n]
            forme = _norm(" ".join(m["word"] for m in bloc))
            correct = table.get(forme) or table.get(forme.replace(" ", ""))
            if correct and forme:
                trouve = (n, correct, bloc)
                break
        if trouve:
            n, correct, bloc = trouve
            fin = re.search(r"[.,!?…]+$", bloc[-1]["word"])
            probas = [m["p"] for m in bloc if m.get("p") is not None]
            mot = {**bloc[0], "word": correct + (fin.group(0) if fin else ""),
                   "end": bloc[-1]["end"]}
            if probas:   # un nom reconnu dans le dictionnaire est fiable
                mot["p"] = max(max(probas), 0.9)
            sortie.append(mot)
            i += n
        else:
            sortie.append(mots[i])
            i += 1
    return sortie


def corriger_transcription(tr: dict, noms: list[str] | None = None) -> dict:
    table = dictionnaire(noms)
    for s in tr.get("segments", []):
        s["words"] = corriger_mots(s.get("words", []), table)
        if s["words"]:
            s["text"] = " ".join(m["word"] for m in s["words"])
    return tr
