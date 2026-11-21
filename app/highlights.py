"""Sélection des moments viraux : Claude lit la transcription et choisit les clips."""
from __future__ import annotations

import json
import os
import re

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

SYSTEM = """Tu es un monteur expert en contenus courts viraux (TikTok, Reels, YouTube Shorts).
On te donne la transcription horodatée d'une vidéo longue. Ta mission : repérer les passages
qui feront les meilleurs shorts autonomes.

Chaque ligne est au format [début-fin | E#] texte. E# est le niveau sonore du passage, de E0
(calme) à E9 (très fort). Un E élevé signale des rires, des cris, une montée de ton, une
réaction vive ou un moment d'action : ce sont souvent les meilleurs moments, et le texte seul
ne les montre pas. Croise toujours les deux : un passage fort ET bien dit vaut mieux qu'un
passage seulement bruyant. Un E bas n'est pas rédhibitoire si le propos est excellent.

Un bon clip :
- commence par un HOOK fort dès la première phrase (question, affirmation choc, chiffre, conflit,
  début d'histoire) — jamais au milieu d'une phrase ni par "et donc", "du coup", "voilà" ;
- se comprend sans le reste de la vidéo ;
- contient un payoff : chute, révélation, punchline, conseil concret, émotion forte, moment drôle ;
- se termine proprement à la fin d'une phrase, idéalement sur le payoff.

Évite les intros/outros, les sponsors, les passages techniques sans contexte et les clips qui se
chevauchent. Les timestamps doivent correspondre exactement aux bornes des segments fournis.

Règles supplémentaires :
- Les 3 premières secondes décident de tout : si la première phrase n'accroche pas seule,
  recule le début jusqu'à une vraie phrase d'accroche, ou choisis un autre passage.
- Répartis les clips sur toute la durée de la vidéo, sans en concentrer plusieurs sur la même
  séquence. Un seul clip par moment fort.
- Ne mets jamais un clip au milieu d'une phrase, ni au début ni à la fin.
- Classe du plus fort au plus faible et sois sévère dans les notes : réserve 85+ aux passages
  dont tu es certain, et n'hésite pas à descendre sous 50 un passage moyen.

Le titre, le hook et la description sont dans la langue de la vidéo."""

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number", "description": "début en secondes"},
                    "end": {"type": "number", "description": "fin en secondes"},
                    "title": {"type": "string", "description": "titre accrocheur, max 60 caractères"},
                    "hook": {"type": "string", "description": "texte à afficher en haut du short, max 8 mots"},
                    "description": {"type": "string", "description": "légende prête à poster"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "virality_score": {"type": "integer", "description": "0 à 100"},
                    "reason": {"type": "string", "description": "pourquoi ce passage peut marcher"},
                },
                "required": ["start", "end", "title", "hook", "description", "hashtags",
                             "virality_score", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def _blocks(segments: list[dict], cible: float = 12.0) -> list[dict]:
    """Regroupe les segments en blocs d'environ `cible` secondes.

    Une vidéo de 3 h fait des milliers de lignes : les regrouper réduit fortement le coût
    et donne à l'IA un texte plus lisible. Les bornes exactes sont recalées ensuite.
    """
    blocs: list[dict] = []
    for s in segments:
        if blocs and s["end"] - blocs[-1]["start"] <= cible:
            b = blocs[-1]
            b["end"] = s["end"]
            b["text"] += " " + s["text"]
            b["e"].append(s.get("e"))
        else:
            blocs.append({"start": s["start"], "end": s["end"], "text": s["text"],
                          "e": [s.get("e")]})
    for b in blocs:
        niveaux = [x for x in b["e"] if x is not None]
        # on garde le PIC du bloc : un éclat de rire ne doit pas être noyé par la moyenne
        b["e"] = max(niveaux) if niveaux else None
    return blocs


def annotate_energy(segments: list[dict], energy: list[float], window: float = 1.0) -> None:
    """Attribue à chaque segment un niveau sonore relatif de 0 à 9."""
    if not energy or not segments:
        return
    import numpy as np

    moyennes = []
    for s in segments:
        i0 = int(s["start"] / window)
        i1 = max(int(s["end"] / window) + 1, i0 + 1)
        part = energy[i0:i1]
        moyennes.append(float(np.mean(part)) if len(part) else -60.0)
    arr = np.array(moyennes)
    rangs = arr.argsort().argsort()                      # position de chaque segment
    niveaux = (rangs / max(len(arr) - 1, 1) * 9).round().astype(int)
    for s, n in zip(segments, niveaux):
        s["e"] = int(n)


def _transcript_text(segments: list[dict]) -> str:
    lignes = []
    for s in _blocks(segments):
        e = f" | E{s['e']}" if s.get("e") is not None else ""
        lignes.append(f"[{s['start']:.1f}-{s['end']:.1f}{e}] {s['text'].strip()}")
    return "\n".join(lignes)


def ask_claude(segments, title, n, min_d, max_d) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic()
    prompt = (
        f"Titre de la vidéo : {title}\n"
        f"Trouve les {n} meilleurs moments pour des shorts de {min_d} à {max_d} secondes, "
        f"classés du plus viral au moins viral.\n\n<transcription>\n{_transcript_text(segments)}\n</transcription>"
    )
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude a refusé d'analyser cette vidéo.")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)["clips"]


HOOK_WORDS = re.compile(
    r"\b(incroyable|secret|jamais|personne|pourquoi|comment|vérité|erreur|argent|millions?|"
    r"choqu|fou|dingue|attention|never|secret|why|how|truth|mistake|money|crazy|insane)\w*",
    re.I,
)


def heuristic(segments, title, n, min_d, max_d) -> list[dict]:
    """Repli sans clé API : densité de parole + mots d'accroche + ponctuation forte."""
    candidates = []
    for i, seg in enumerate(segments):
        j, text = i, []
        while j < len(segments) and segments[j]["end"] - seg["start"] <= max_d:
            text.append(segments[j]["text"])
            j += 1
            dur = segments[j - 1]["end"] - seg["start"]
            if dur < min_d:
                continue
            body = " ".join(text)
            words = len(body.split())
            score = words / dur * 10 + 8 * len(HOOK_WORDS.findall(body)) + 4 * body.count("?") + 3 * body.count("!")
            score += 15 * bool(HOOK_WORDS.search(seg["text"]) or "?" in seg["text"])
            candidates.append((score, seg["start"], segments[j - 1]["end"], body))
    candidates.sort(reverse=True)
    picked: list[tuple] = []
    for c in candidates:
        if all(c[2] <= p[1] or c[1] >= p[2] for p in picked):
            picked.append(c)
        if len(picked) == n:
            break
    top = picked[0][0] if picked else 1
    return [{
        "start": s, "end": e,
        "title": body[:57] + ("…" if len(body) > 57 else ""),
        "hook": " ".join(body.split()[:6]),
        "description": f"Extrait de « {title} »",
        "hashtags": ["#shorts", "#viral", "#fyp"],
        "virality_score": int(60 * sc / top) + 20,
        "reason": "Sélection automatique (mode sans IA) : passage dense et accrocheur.",
    } for sc, s, e, body in picked]


def _snap(clips, segments, duration, min_d, max_d) -> list[dict]:
    """Aligne les bornes sur les phrases, borne la durée, supprime les chevauchements."""
    starts = [s["start"] for s in segments]
    ends = [s["end"] for s in segments]
    out = []
    for c in sorted(clips, key=lambda c: -c.get("virality_score", 0)):
        s = min(starts, key=lambda x: abs(x - c["start"]))
        e = min(ends, key=lambda x: abs(x - c["end"]))
        if e - s > max_d:
            e = max([x for x in ends if x - s <= max_d] or [s + max_d])
        if e - s < min_d * 0.7:
            continue
        s, e = max(0.0, s - 0.15), min(duration, e + 0.35)
        if any(not (e <= o["start"] or s >= o["end"]) for o in out):
            continue
        out.append({**c, "start": round(s, 2), "end": round(e, 2)})
    return out


def find_moments(segments, title, duration, n=8, min_d=20, max_d=60,
                 energy: list[float] | None = None) -> tuple[list[dict], str, str]:
    if not segments:
        return [], "aucune parole détectée", ""
    annotate_energy(segments, energy or [])
    engine, note = "claude", ""
    try:
        if not (os.getenv("ANTHROPIC_API_KEY") or "").startswith("sk-ant-"):
            raise RuntimeError("aucune clé ANTHROPIC_API_KEY valide dans le fichier .env")
        clips = ask_claude(segments, title, n, min_d, max_d)
    except Exception as exc:  # repli hors-ligne
        note = _explain(exc)
        print(f"[highlights] Claude indisponible ({note}), repli heuristique")
        engine = "heuristique"
        clips = heuristic(segments, title, n, min_d, max_d)
    return _snap(clips, segments, duration, min_d, max_d)[:n], engine, note


def _explain(exc: Exception) -> str:
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return "clé API refusée (vérifie qu'elle est complète dans .env)"
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "accès refusé par l'API (compte ou clé)"
    if isinstance(exc, anthropic.BadRequestError) and "credit" in str(exc).lower():
        return "crédits épuisés : ajoute des crédits sur console.anthropic.com"
    if isinstance(exc, anthropic.RateLimitError):
        return "trop de requêtes, réessaie dans une minute"
    if isinstance(exc, anthropic.APIConnectionError):
        return "impossible de joindre l'API (connexion internet ?)"
    return str(exc)[:200]
