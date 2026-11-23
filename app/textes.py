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
    if not jeu.strip():
        return ""
    return f"{streamer.strip()} en plein live sur {jeu.strip()}" if streamer.strip() else f"En plein live sur {jeu.strip()}"


def _tag(texte: str) -> str:
    return "#" + re.sub(r"[^a-z0-9]", "", _sans_accents(texte).lower())


def hashtags(texte: str, streamer: str = "", jeu: str = "", langue: str | None = "fr") -> list[str]:
    """3 à 5 hashtags ciblés : le jeu, le streamer, le sujet. Jamais #drole, #yt, #creator…"""
    tags = []
    if jeu.strip():
        tags.append(_tag(jeu))
        if (langue or "fr").startswith("fr"):
            tags.append(_tag(jeu) + "fr")
    if streamer.strip():
        tags.append(_tag(streamer))
    s = sujet(texte)
    if s:
        tags.append(s[3])
    if len(tags) < 3 and jeu.strip():
        tags.append(_tag(jeu) + "clips")
    if len(tags) < 3:
        tags.append("#gaming")
    propres = [t for t in dict.fromkeys(tags) if len(t) > 2 and t.lower() not in INTERDITS]
    return propres[:5]


def titre(texte: str, streamer: str = "", jeu: str = "") -> str:
    """Titre qui contient ce qu'on tape dans la recherche : streamer, jeu, sujet."""
    s = sujet(texte)
    if s:
        t = f"{streamer.strip() or 'Il'} {s[2]}"
    else:
        t = f"{streamer.strip()} en plein live" if streamer.strip() else "En plein live"
    if jeu.strip():
        t += f" sur {jeu.strip()}"
    citation = _citation(texte)
    if citation and len(t) + len(citation) + 5 <= 100:
        t += f" : « {citation} »"
    return t[:100]


def nettoyer_legende(texte: str, tags: list[str], extra: list[str] | None = None) -> str:
    """Retire les hashtags vagues ou inventés et met les hashtags ciblés à la fin."""
    sans = re.sub(r"(?<!\w)#[\wÀ-ſ]+", "", texte or "")
    sans = re.sub(r"[ \t]{2,}", " ", sans).strip()
    fin = " ".join(list(dict.fromkeys(tags + (extra or []))))
    return f"{sans}\n\n{fin}".strip() if sans else fin


def legendes(clip: dict, texte: str, streamer: str = "", jeu: str = "",
             langue: str | None = "fr") -> dict:
    """Titre, hashtags et légendes par plateforme, à partir du texte du clip."""
    tags = hashtags(texte, streamer, jeu, langue)
    t = titre(texte, streamer, jeu)
    caps = clip.get("captions") or {}
    credit = f"Clip du live de {streamer.strip()}" if streamer.strip() else ""

    def avec_titre(autre: str) -> str:
        # le titre précis d'abord (c'est lui qu'on trouve en recherche), le reste ensuite
        reste = re.sub(r"(?<!\w)#[\w\u00C0-\u017F]+", "", autre or "").strip()
        return f"{t}\n{reste}" if reste and reste.lower() not in t.lower() else t

    return {
        "title": t,
        "hashtags": tags,
        "captions": {
            "tiktok": nettoyer_legende(avec_titre(caps.get("tiktok", "")), tags),
            "youtube": nettoyer_legende(f"{t}\n{credit}", tags, ["#Shorts"]),
            "reels": nettoyer_legende(t, tags),
        },
        "description": nettoyer_legende(f"{t}\n{credit}", tags),
    }
