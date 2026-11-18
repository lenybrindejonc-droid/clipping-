"""Recadrage automatique 16:9 → 9:16 qui suit le visage principal."""
from __future__ import annotations

from pathlib import Path

SAMPLE_EVERY = 0.5   # secondes entre deux analyses d'image
MOVE_THRESHOLD = 0.08  # fraction de la largeur avant de déplacer le cadre
TRANSITION = 0.35    # durée d'un mouvement de caméra (s)


def _face_centers(src: Path, start: float, end: float, src_w: int) -> list[tuple[float, float | None]]:
    import cv2

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(str(src))
    samples: list[tuple[float, float | None]] = []
    t = start
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        scale = 480 / frame.shape[1]
        small = cv2.resize(frame, None, fx=scale, fy=scale)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=6, minSize=(30, 30))
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])  # le plus grand visage
            samples.append((t - start, (x + w / 2) / scale))
        else:
            samples.append((t - start, None))
        t += SAMPLE_EVERY
    cap.release()
    return samples


def crop_x_expression(src: Path, start: float, end: float, src_w: int, src_h: int, crop_w: int) -> str:
    """Retourne une expression ffmpeg x(t) pour le filtre crop.

    Le cadre reste fixe tant que le visage ne bouge pas beaucoup, puis glisse
    rapidement vers la nouvelle position (comme un monteur humain).
    """
    max_x = src_w - crop_w
    center = src_w / 2
    try:
        samples = _face_centers(src, start, end, src_w)
    except Exception:
        samples = []

    # Remplit les trous (pas de visage) avec la dernière position connue
    known = [c for _, c in samples if c is not None]
    if not known:
        return str(max_x // 2)
    last = known[0]
    filled = []
    for t, c in samples:
        last = c if c is not None else last
        filled.append((t, last))

    # Lissage médian sur 3 échantillons
    smooth = []
    for i, (t, _) in enumerate(filled):
        win = sorted(c for _, c in filled[max(0, i - 1): i + 2])
        smooth.append((t, win[len(win) // 2]))

    # Positions "plans fixes"
    def to_x(c: float) -> int:
        return int(min(max(c - crop_w / 2, 0), max_x))

    keys = [(0.0, to_x(smooth[0][1]))]
    for t, c in smooth[1:]:
        x = to_x(c)
        if abs(x - keys[-1][1]) > MOVE_THRESHOLD * src_w:
            keys.append((t, x))

    if len(keys) == 1:
        return str(keys[0][1])

    # Expression par morceaux : plan fixe, puis glissement linéaire vers le plan suivant
    def ramp(i: int) -> str:
        t1, x1 = keys[i]
        x0 = keys[i - 1][1]
        return f"{x0}+({x1 - x0})*(t-{t1:.2f})/{TRANSITION}"

    def segment(i: int) -> str:  # valable pour t >= keys[i].t
        t1, x1 = keys[i]
        body = f"if(lt(t,{t1 + TRANSITION:.2f}),{ramp(i)},{x1})"
        if i + 1 < len(keys):
            return f"if(lt(t,{keys[i + 1][0]:.2f}),{body},{segment(i + 1)})"
        return body

    return f"if(lt(t,{keys[1][0]:.2f}),{keys[0][1]},{segment(1)})"
