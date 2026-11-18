"""Sélection des moments viraux : Claude lit la transcription et choisit les clips."""
from __future__ import annotations

import json
import os
import re

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

SYSTEM = """Tu es un monteur expert en contenus courts viraux (TikTok, Reels, YouTube Shorts).
On te donne la transcription horodatée d'une vidéo longue. Ta mission : repérer les passages
qui feront les meilleurs shorts autonomes.

Un bon clip :
- commence par un HOOK fort dès la première phrase (question, affirmation choc, chiffre, conflit,
  début d'histoire) — jamais au milieu d'une phrase ni par "et donc", "du coup", "voilà" ;
- se comprend sans le reste de la vidéo ;
- contient un payoff : chute, révélation, punchline, conseil concret, émotion forte, moment drôle ;
- se termine proprement à la fin d'une phrase, idéalement sur le payoff.

Évite les intros/outros, les sponsors, les passages techniques sans contexte et les clips qui se
chevauchent. Les timestamps doivent correspondre exactement aux bornes des segments fournis.
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


def _transcript_text(segments: list[dict]) -> str:
    return "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segments)


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
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
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


def find_moments(segments, title, duration, n=8, min_d=20, max_d=60) -> tuple[list[dict], str]:
    if not segments:
        return [], "aucune parole détectée"
    engine = "claude"
    try:
        if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            raise RuntimeError("pas de clé API")
        clips = ask_claude(segments, title, n, min_d, max_d)
    except Exception as exc:  # repli hors-ligne
        print(f"[highlights] Claude indisponible ({exc}), repli heuristique")
        engine = "heuristique"
        clips = heuristic(segments, title, n, min_d, max_d)
    return _snap(clips, segments, duration, min_d, max_d)[:n], engine
