"""Accroche, titre et hashtags fabriqués à partir de ce qui est DIT dans le clip.

Gratuit (aucune IA) : on repère le sujet du clip avec une liste de mots (police, crash,
braquage…) et on écrit une phrase simple qui dit ce qui se passe vraiment.
Si Claude a proposé des accroches, on garde la meilleure qui tient en 4 à 7 mots.
"""
from __future__ import annotations

import re
import unicodedata

# sujet : (mots qui le trahissent, ce qui se passe, hashtag ciblé, mot qu'on cherche)
SUJETS = [
    ("poursuite", r"\b(police|flics?|keufs?|condés?|poursuite|course[- ]poursuite|sirènes?|cops?|chase)\b",
     "fuit la police", "#poursuite", "course-poursuite"),
    ("braquage", r"\b(braqu\w*|banque|casse|heist|coffre|bijouterie|superette|supérette)\b",
     "tente un braquage", "#braquage", "braquage"),
    ("crash", r"\b(crash\w*|accident|carambolage|percut\w*|tonneaux?|explos\w*|boum)\b",
     "fait un crash énorme", "#crash", "crash"),
    ("arrestation", r"\b(arrêt\w*|menott\w*|prison|cellule|garde à vue|busted)\b",
     "se fait arrêter", "#arrestation", "arrestation"),
    ("mort", r"\b(mort|meurt|tué|tuer|abattu|wasted|dead|il m'a tué|je suis mort)\b",
     "se fait éliminer", "#gtafail", "mort"),
    ("cascade", r"\b(cascade|saut|parachute|moto|wheeling|stunt|avion|hélico\w*)\b",
     "tente une cascade folle", "#cascade", "cascade"),
    ("rp", r"\b(rp|roleplay|serveur|personnage|métier|mairie|concessionnaire)\b",
     "part en roleplay", "#gtarp", "roleplay"),
    ("fou_rire", r"\b(mdr|ptdr|jpp|je suis mort de rire|c'est trop drôle|lol|xd)\b",
     "part en fou rire", "#fourire", "fou rire"),
]
# Hashtags trop vagues : ils ne ciblent personne (demande de l'utilisateur)
INTERDITS = {"#drole", "#drôle", "#yt", "#creator", "#fyp", "#foryou", "#foryoupage", "#pourtoi",
             "#viral", "#tiktok", "#trend", "#humour", "#funny", "#lol", "#video", "#clip"}
EMOJIS = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")


def sans_emojis(texte: str) -> str:
    """Les emojis incrustés sortent en noir et blanc : on les retire de l'image."""
    return re.sub(r"\s{2,}", " ", EMOJIS.sub("", texte)).strip()


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))


def sujet(texte: str) -> tuple | None:
    """Le sujet le plus présent dans le texte du clip, ou None."""
    meilleur, compte = None, 0
    for s in SUJETS:
        n = len(re.findall(s[1], texte, re.I))
        if n > compte:
            meilleur, compte = s, n
    return meilleur


def _citation(texte: str) -> str:
    """4 à 7 mots réellement dits, pris au début du clip (là où est le moment fort)."""
    mots = [m for m in re.sub(r"[«»\"]", "", texte).split() if m]
    return " ".join(mots[:7]) if len(mots) >= 4 else ""


def accroche(texte: str, streamer: str = "", jeu: str = "", proposees: list[str] | None = None) -> str:
    """Accroche de 4 à 7 mots qui dit ce qui se passe vraiment."""
    for p in proposees or []:
        p = sans_emojis(p).strip(" .")
        if 4 <= len(p.split()) <= 7:
            return p
    s = sujet(texte)
    qui = streamer.strip() or "Il"
    if s:
        phrase = f"{qui} {s[2]}"
        if jeu.strip() and len((phrase + ' dans ' + jeu).split()) <= 7:
            phrase += f" dans {jeu.strip()}"
        if len(phrase.split()) >= 4:
            return phrase
        return f"{phrase} en plein live" if len(phrase.split()) <= 4 else phrase
    citation = _citation(texte)
    if citation:
        return f"« {citation} »"
    return f"{qui} en plein live sur {jeu.strip()}" if jeu.strip() else ""
