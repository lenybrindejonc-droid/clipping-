"""Recadrage automatique 16:9 → 9:16.

- Détecteur de visages YuNet (réseau de neurones OpenCV, téléchargé une fois),
  avec repli sur Haar si le téléchargement échoue.
- Mode « auto » : suit la personne si elle est seule à l'écran, sinon garde la
  vidéo entière sur fond flou (podcast à deux, plan large, pas de visage).
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

SAMPLE_EVERY = 0.5       # secondes entre deux analyses d'image
MOVE_THRESHOLD = 0.10    # fraction de la largeur avant de déplacer le cadre
MIN_SHOT = 1.2           # durée minimale d'un plan fixe (s)
TRANSITION = 0.30        # durée d'un mouvement de caméra (s)
DETECT_WIDTH = 640

YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")
MODEL_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data")) / "models"

_detector = None


def _get_detector():
    """Retourne une fonction frame -> liste de (cx, largeur) des visages."""
    global _detector
    if _detector:
        return _detector
    import cv2

    model = MODEL_DIR / "yunet.onnx"
    try:
        if not model.exists():
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(YUNET_URL, model)
        net = cv2.FaceDetectorYN.create(str(model), "", (320, 320), 0.7, 0.3, 50)

        def yunet(img):
            h, w = img.shape[:2]
            net.setInputSize((w, h))
            _, faces = net.detect(img)
            return [] if faces is None else [(f[0] + f[2] / 2, f[2]) for f in faces]

        _detector = yunet
    except Exception as exc:
        print(f"[reframe] YuNet indisponible ({exc}), repli Haar")
        model.unlink(missing_ok=True)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

        def haar(img):
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 8, minSize=(40, 40))
            return [(x + w / 2, w) for x, y, w, h in faces]

        _detector = haar
    return _detector


def _scan(src: Path, start: float, end: float) -> list[tuple[float, list[tuple[float, float]]]]:
    """Pour chaque instant échantillonné : visages (centre x, largeur) en pixels source."""
    import cv2

    detect = _get_detector()
    cap = cv2.VideoCapture(str(src))
    out = []
    t = start
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        scale = DETECT_WIDTH / frame.shape[1]
        small = cv2.resize(frame, None, fx=scale, fy=scale)
        faces = [(cx / scale, w / scale) for cx, w in detect(small)]
        # ignore les petits visages (public, arrière-plan)
        if faces:
            biggest = max(w for _, w in faces)
            faces = [f for f in faces if f[1] >= 0.45 * biggest]
        out.append((t - start, faces))
        t += SAMPLE_EVERY
    cap.release()
    return out


def plan(src: Path, start: float, end: float, src_w: int, crop_w: int) -> str | None:
    """Expression ffmpeg x(t) pour le recadrage, ou None si mieux vaut le plan large."""
    try:
        samples = _scan(src, start, end)
    except Exception as exc:
        print(f"[reframe] analyse impossible ({exc})")
        return None
    if not samples:
        return None

    with_face = [f for _, f in samples if f]
    multi = [f for f in with_face if max(c for c, _ in f) - min(c for c, _ in f) > crop_w * 0.8]
    # Pas assez de visages, ou plusieurs personnes trop éloignées pour tenir dans le cadre
    if len(with_face) < 0.4 * len(samples) or len(multi) > 0.35 * len(samples):
        return None

    max_x = src_w - crop_w

    def to_x(c: float) -> int:
        return int(min(max(c - crop_w / 2, 0), max_x))

    # Centre de la personne principale (le plus grand visage), trous comblés
    centers: list[float | None] = [max(f, key=lambda v: v[1])[0] if f else None for _, f in samples]
    first = next(c for c in centers if c is not None)
    filled, last = [], first
    for c in centers:
        last = c if c is not None else last
        filled.append(last)

    # Lissage médian sur ~2 secondes
    k = max(1, int(1.0 / SAMPLE_EVERY))
    smooth = []
    for i in range(len(filled)):
        win = sorted(filled[max(0, i - k): i + k + 1])
        smooth.append(win[len(win) // 2])

    keys = [(0.0, to_x(smooth[0]))]
    for i, c in enumerate(smooth[1:], 1):
        t, x = samples[i][0], to_x(c)
        if abs(x - keys[-1][1]) > MOVE_THRESHOLD * src_w and t - keys[-1][0] >= MIN_SHOT:
            keys.append((t, x))

    if len(keys) == 1:
        return str(keys[0][1])

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
