"""Sous-titres style TikTok (mot actif surligné) au format ASS."""
from __future__ import annotations

import os
from pathlib import Path

FONT = os.getenv("SUBTITLE_FONT", "Inter")
WORDS_PER_LINE = 3
HIGHLIGHT = "&H0000E5FF&"  # jaune (format ASS : &HAABBGGRR)
MAX_GAP = 0.6    # un blanc plus long coupe le groupe de mots
MAX_CHARS = 16   # au-delà, la ligne passerait sur 2 lignes à l'écran
# Petit retard : un sous-titre légèrement en retard se remarque moins qu'un en avance
DELAY = float(os.getenv("SUBTITLE_DELAY", "0.08"))
HOLD = 0.35      # le dernier mot d'une phrase reste un peu après avoir été prononcé


def _fix_timing(words: list[dict]) -> list[dict]:
    """Corrige les horodatages de Whisper.

    - supprime les doublons (même mot compté deux fois) ;
    - Whisper fait souvent « commencer » un mot pendant le silence qui le précède,
      d'où des sous-titres en avance : on raccourcit les mots anormalement longs par le début ;
    - garantit un ordre strict, sans chevauchement.
    """
    out: list[dict] = []
    for w in sorted(words, key=lambda x: (x["start"], x["end"])):
        if out and w["word"] == out[-1]["word"] and abs(w["start"] - out[-1]["start"]) < 0.3:
            continue
        start, end = w["start"], max(w["end"], w["start"] + 0.05)
        longest = min(0.15 + 0.08 * len(w["word"]), 1.2)
        if end - start > longest:
            start = end - longest
        if out:
            start = max(start, out[-1]["start"] + 0.05)
        out.append({**w, "start": start + DELAY, "end": max(end, start + 0.05) + DELAY})
    return out


def _ts(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(word: str) -> str:
    return word.replace("{", "").replace("}", "").replace("\\", "").upper()


def write_ass(
    path: Path, words: list[dict], clip_start: float, clip_end: float, w: int, h: int,
    hook: str | None = None,
    sub_pos: tuple[int, int] | None = None,
    hook_pos: tuple[int, int] | None = None,
    style: dict | None = None,
) -> None:
    style = style or {}
    mots_max = int(style.get("mots", WORDS_PER_LINE))
    taille = int(style.get("taille", 96))
    hauteur = float(style.get("hauteur", 0.27))
    chars_max = MAX_CHARS + 6 * (mots_max - WORDS_PER_LINE)
    sub_tag = f"{{\\an5\\pos({sub_pos[0]},{sub_pos[1]})}}" if sub_pos else ""
    hook_tag = f"{{\\an5\\pos({hook_pos[0]},{hook_pos[1]})}}" if hook_pos else ""
    words = [x for x in _fix_timing(words) if x["end"] > clip_start and x["start"] < clip_end]

    # Regroupe les mots en petites lignes
    groups: list[list[dict]] = []
    for word in words:
        if (
            not groups
            or len(groups[-1]) >= mots_max
            or sum(len(w["word"]) + 1 for w in groups[-1]) + len(word["word"]) > chars_max
            or word["start"] - groups[-1][-1]["end"] > MAX_GAP
            or groups[-1][-1]["word"].endswith((".", "?", "!"))
        ):
            groups.append([])
        groups[-1].append(word)

    # (début, fin, texte) pour chaque mot ; une seule ligne à l'écran à la fois
    timeline: list[list] = []
    for group in groups:
        for i, word in enumerate(group):
            start = word["start"] - clip_start
            # le mot reste affiché jusqu'au début du suivant (pas de clignotement)
            end = (group[i + 1]["start"] if i + 1 < len(group) else word["end"] + HOLD) - clip_start
            parts = []
            for j, other in enumerate(group):
                text = _clean(other["word"])
                parts.append(
                    f"{{\\c{HIGHLIGHT}\\fscx110\\fscy110}}{text}{{\\c&H00FFFFFF&\\fscx100\\fscy100}}"
                    if j == i else text
                )
            pop = "{\\t(0,80,\\fscx104\\fscy104)\\t(80,160,\\fscx100\\fscy100)}" if i == 0 else ""
            timeline.append([max(start, 0.0), end, f"{sub_tag}{pop}{' '.join(parts)}"])

    events = []
    for k, (start, end, text) in enumerate(timeline):
        if k + 1 < len(timeline):
            end = min(end, timeline[k + 1][0])  # jamais deux sous-titres superposés
        end = min(end, clip_end - clip_start)
        if end - start >= 0.04:
            events.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Main,,0,0,0,,{text}")

    if hook:
        # Bandeau visible pendant les 4 premières secondes (le moment où on décide de scroller)
        hook_end = min(4.0, clip_end - clip_start)
        events.insert(0, f"Dialogue: 1,{_ts(0)},{_ts(hook_end)},Hook,,0,0,0,,"
                         f"{hook_tag}{{\\fad(120,300)}}{_clean(hook)}")

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{FONT},{taille},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,2,2,60,60,{int(h * hauteur)},1
Style: Hook,{FONT},64,&H00111111,&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,90,90,{int(h * 0.12)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
