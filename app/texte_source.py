"""Repère le texte déjà incrusté dans la vidéo source (sous-titres d'origine, alertes,
bandeaux, commandes du chat) pour le flouter : sinon il se superpose à nos sous-titres.

Méthode légère (OpenCV, sans modèle) : sur quelques images du clip, on cherche les zones
« qui ressemblent à du texte » (beaucoup de contours fins, alignés à l'horizontale).
On ne floute que les zones présentes sur une bonne partie des images : un texte incrusté
reste en place, alors qu'un décor du jeu bouge.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

LARGEUR = 640          # analyse en petit : rapide, même sur un Chromebook
IMAGES = 8             # images analysées par clip
PRESENCE = 0.4         # zone gardée si elle est « texte » sur 40 % des images ou plus
SURFACE_MAX = 0.2      # on ne floute jamais plus de 20 % de l'image
ZONES_MAX = 6


def _images(src: Path, start: float, end: float, w: int, h: int):
    import numpy as np

    hauteur = int(h * LARGEUR / w) // 2 * 2
    pas = max((end - start) / IMAGES, 0.5)
    for k in range(IMAGES):
        t = start + pas * (k + 0.5)
        if t >= end:
            break
        brut = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
             "-vf", f"scale={LARGEUR}:{hauteur},format=gray", "-f", "rawvideo", "-"],
            capture_output=True).stdout
        if len(brut) == LARGEUR * hauteur:
            yield np.frombuffer(brut, np.uint8).reshape(hauteur, LARGEUR)


def _bandes(bw, x, y, w, h, hmin, hmax):
    """Découpe un bloc trop haut en bandes horizontales de texte (lignes)."""
    import numpy as np

    ligne = (bw[y:y + h, x:x + w] > 0).mean(axis=1)
    actif = ligne > max(0.12, float(np.median(ligne)) * 1.5)
    bandes, debut = [], None
    for k, a in enumerate(list(actif) + [False]):
        if a and debut is None:
            debut = k
        elif not a and debut is not None:
            if hmin <= k - debut <= hmax:
                bandes.append((y + debut, k - debut))
            debut = None
    sortie = []
    for by, bh in bandes:
        cols = np.nonzero((bw[by:by + bh, x:x + w] > 0).mean(axis=0) > 0.1)[0]
        if len(cols):
            sortie.append((x + int(cols.min()), by, int(cols.max() - cols.min()) + 1, bh))
    return sortie


def _masque_texte(img):
    """Masque des zones qui ressemblent à du texte sur une image en gris."""
    import cv2
    import numpy as np

    h = img.shape[0]
    hmin, hmax = int(0.015 * h), int(0.12 * h)
    grad = cv2.morphologyEx(img, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    lie = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3)))
    contours, _ = cv2.findContours(lie, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    masque = np.zeros_like(img)
    for c in contours:
        x, y, bw_, bh = cv2.boundingRect(c)
        # bloc trop haut : le texte touche le décor → on cherche ses lignes à l'intérieur
        boites = _bandes(bw, x, y, bw_, bh, hmin, hmax) if bh > hmax and bw_ > 3 * hmin else [(x, y, bw_, bh)]
        for x2, y2, w2, h2 in boites:
            if not (hmin <= h2 <= hmax and w2 >= 2.5 * h2):
                continue
            densite = cv2.countNonZero(bw[y2:y2 + h2, x2:x2 + w2]) / float(w2 * h2)
            if 0.2 <= densite <= 0.9:          # du texte : ni vide, ni un aplat
                masque[y2:y2 + h2, x2:x2 + w2] = 1
    return masque


def zones_texte(src: Path, start: float, end: float, w: int, h: int,
                exclure: tuple[int, int, int, int] | None = None) -> list[tuple[int, int, int, int]]:
    """Rectangles (x, y, largeur, hauteur) du texte incrusté, en pixels de la source.

    `exclure` : zone à ne jamais flouter (la facecam)."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []
    masques = [_masque_texte(img) for img in _images(src, start, end, w, h)]
    if len(masques) < 3:
        return []
    frequence = np.mean(masques, axis=0)
    stable = (frequence >= PRESENCE).astype(np.uint8)
    stable = cv2.dilate(stable, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(stable)
    echelle = w / LARGEUR
    zones, surface = [], 0.0
    for x, y, bw, bh, aire in sorted(stats[1:].tolist(), key=lambda s: -s[4]):
        if aire < 40:
            continue
        X, Y = int(x * echelle) - 6, int(y * echelle) - 6
        W, H = int(bw * echelle) + 12, int(bh * echelle) + 12
        X, Y = max(0, X), max(0, Y)
        W, H = min(W, w - X) // 2 * 2, min(H, h - Y) // 2 * 2
        if exclure:
            fx, fy, fw, fh = exclure
            if X < fx + fw and fx < X + W and Y < fy + fh and fy < Y + H:
                continue
        if (surface + W * H) / (w * h) > SURFACE_MAX or W < 8 or H < 8:
            continue
        surface += W * H
        zones.append((X, Y, W, H))
        if len(zones) >= ZONES_MAX:
            break
    return zones


def filtre_flou(zones: list[tuple[int, int, int, int]], entree: str = "[0:v]",
                sortie: str = "[src]") -> str:
    """Chaîne ffmpeg qui floute fortement chaque zone (entree → sortie)."""
    if not zones:
        return ""
    parties, courant = [], entree
    for k, (x, y, w, h) in enumerate(zones):
        nxt = sortie if k == len(zones) - 1 else f"[m{k}]"
        parties.append(f"{courant}split[ma{k}][mb{k}];[mb{k}]crop={w}:{h}:{x}:{y},"
                       f"boxblur={max(2, min(w, h) // 4)}:3[bl{k}];[ma{k}][bl{k}]overlay={x}:{y}{nxt}")
        courant = nxt
    return ";".join(parties)
