"""Contrôle de chaque clip avant export : un rapport lisible, et les clips ratés mis de côté.

Un clip « mis de côté » reste visible sur le site (pour comprendre pourquoi), mais il n'est
ni dans le zip, ni dans la bibliothèque, ni programmé : on ne publie que ce qui passe.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .subtitles import SEUIL_CLIP

DUREE_MIN, DUREE_MAX = 8.0, 30.0
SCORE_MIN = int(os.getenv("SCORE_MIN", "50"))
CONFIANCE_A_RELIRE = 0.75


def _sonde(fichier: Path) -> dict:
    """Largeur, hauteur, durée et présence du son du fichier réellement produit."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
         "-of", "json", str(fichier)], capture_output=True, text=True)
    try:
        d = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {}
    video = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    return {"w": video.get("width"), "h": video.get("height"),
            "duree": float(d.get("format", {}).get("duration") or 0),
            "son": any(s.get("codec_type") == "audio" for s in d.get("streams", []))}


def controler(clip: dict, fichier: Path, req: dict) -> dict:
    """Renvoie le rapport du clip ; rapport["echecs"] non vide = clip mis de côté."""
    echecs, alertes = [], []
    duree = round(clip["end"] - clip["start"], 1)
    score = clip.get("virality_score")
    conf = clip.get("confiance_sous_titres")

    if duree < DUREE_MIN:
        echecs.append(f"trop court ({duree} s, minimum {DUREE_MIN:.0f} s)")
    elif duree > DUREE_MAX:
        echecs.append(f"trop long ({duree} s, maximum {DUREE_MAX:.0f} s : les gens partent avant la fin)")
    if score is not None and score < SCORE_MIN:
        echecs.append(f"score trop faible ({score}/100, minimum {SCORE_MIN})")
    if req.get("show_hook", True) and not (clip.get("hook_on_video") or "").strip():
        echecs.append("pas d'accroche sur la première image")

    info = _sonde(fichier) if fichier.exists() else {}
    if not info:
        echecs.append("fichier vidéo absent ou illisible")
    else:
        if (info["w"], info["h"]) != (1080, 1920):
            echecs.append(f"format {info['w']}×{info['h']} au lieu de 1080×1920 (vertical)")
        if abs(info["duree"] - duree) > 1.5:
            echecs.append(f"durée du fichier ({info['duree']:.1f} s) différente de celle prévue")
        if not info["son"]:
            echecs.append("pas de son")

    if req.get("subtitles", True):
        if conf is None:
            alertes.append("confiance des sous-titres inconnue (ancienne transcription)")
        elif conf < SEUIL_CLIP:
            alertes.append(f"sous-titres retirés : transcription trop incertaine ({conf:.0%})")
        elif conf < CONFIANCE_A_RELIRE:
            alertes.append(f"sous-titres à relire : confiance moyenne ({conf:.0%})")
    if clip.get("pic") is not None and clip["pic"] > 2.5:
        alertes.append(f"le moment fort arrive à {clip['pic']:.1f} s : risque que les gens partent avant")
    if clip.get("texte_source_floute"):
        alertes.append(f"{clip['texte_source_floute']} zone(s) de texte de la source floutée(s) : "
                       "vérifie que rien d'important n'est caché")
    if clip.get("spoiler"):
        alertes.append("dévoile l'histoire du jeu")
    for v in clip.get("campaign_check") or []:
        if v.get("verdict") == "probleme":
            alertes.append(f"règle de campagne : {v.get('regle')} — {v.get('detail')}")

    return {
        "duree": duree,
        "score": score,
        "confiance_sous_titres": conf,
        "sous_titres": ("affichés" if req.get("subtitles", True) and (conf is None or conf >= SEUIL_CLIP)
                        else "non affichés"),
        "avertissements": alertes,
        "echecs": echecs,
    }


def texte(rapport: dict) -> list[str]:
    """Le rapport en lignes lisibles (textes.md, interface)."""
    conf = rapport.get("confiance_sous_titres")
    lignes = [f"Durée {rapport['duree']} s · score {rapport.get('score', '?')}/100 · sous-titres "
              f"{rapport['sous_titres']}" + (f" (confiance {conf:.0%})" if conf is not None else "")]
    lignes += [f"⛔ {e}" for e in rapport.get("echecs", [])]
    lignes += [f"⚠️ {a}" for a in rapport.get("avertissements", [])]
    return lignes
