"""Sous-titres style TikTok (mot actif surligné) au format ASS."""
from __future__ import annotations

import os
from pathlib import Path

FONT = os.getenv("SUBTITLE_FONT", "Inter")
WORDS_PER_LINE = 3
HIGHLIGHT = "&H0000E5FF&"  # jaune (format ASS : &HAABBGGRR)
MAX_GAP = 0.6  # un blanc plus long coupe le groupe de mots


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
) -> None:
    words = [x for x in words if x["end"] > clip_start and x["start"] < clip_end]

    # Regroupe les mots en petites lignes
    groups: list[list[dict]] = []
    for word in words:
        if (
            not groups
            or len(groups[-1]) >= WORDS_PER_LINE
            or word["start"] - groups[-1][-1]["end"] > MAX_GAP
            or groups[-1][-1]["word"].endswith((".", "?", "!"))
        ):
            groups.append([])
        groups[-1].append(word)

    events = []
    for group in groups:
        for i, word in enumerate(group):
            start = word["start"] - clip_start
            # le mot reste affiché jusqu'au début du suivant (pas de clignotement)
            end = (group[i + 1]["start"] if i + 1 < len(group) else word["end"]) - clip_start
            end = min(end, clip_end - clip_start)
            if end <= start:
                continue
            parts = []
            for j, other in enumerate(group):
                text = _clean(other["word"])
                parts.append(
                    f"{{\\c{HIGHLIGHT}\\fscx110\\fscy110}}{text}{{\\c&H00FFFFFF&\\fscx100\\fscy100}}"
                    if j == i else text
                )
            pop = "{\\t(0,80,\\fscx104\\fscy104)\\t(80,160,\\fscx100\\fscy100)}" if i == 0 else ""
            events.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Main,,0,0,0,,{pop}{' '.join(parts)}")

    if hook:
        # Bandeau d'accroche en haut de l'écran pendant tout le clip
        events.insert(0, f"Dialogue: 1,{_ts(0)},{_ts(clip_end - clip_start)},Hook,,0,0,0,,"
                         f"{{\\fad(150,0)}}{_clean(hook)}")

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{FONT},86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,3,2,60,60,{int(h * 0.27)},1
Style: Hook,{FONT},64,&H00111111,&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,90,90,{int(h * 0.12)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
