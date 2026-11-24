"""Recadrage automatique 16:9 → 9:16.

- Détecteur de visages YuNet (réseau de neurones OpenCV, téléchargé une fois),
  avec repli sur Haar si le téléchargement échoue.
- Mode « auto » : écran partagé facecam/jeu pour le gaming, suit la personne si
  elle est seule à l'écran, sinon vidéo entière sur fond flou.
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

SAMPLE_EVERY = 0.5       # secondes entre deux analyses d'image
MOVE_THRESHOLD = 0.10    # fraction de la largeur avant de déplacer le cadre
MIN_SHOT = 1.2           # durée minimale d'un plan fixe (s)
TRANSITION = 0.30        # durée d'un mouvement de caméra (s)
FACECAM_H = 700          # hauteur du bandeau facecam en mode gaming (sur 1920)
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
            return [] if faces is None else [(f[0] + f[2] / 2, f[1] + f[3] / 2, f[2]) for f in faces]

        _detector = yunet
    except Exception as exc:
        print(f"[reframe] YuNet indisponible ({exc}), repli Haar")
        model.unlink(missing_ok=True)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

        def haar(img):
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 8, minSize=(40, 40))
            return [(x + w / 2, y + h / 2, w) for x, y, w, h in faces]

        _detector = haar
    return _detector


def _scan(src: Path, start: float, end: float) -> list[tuple[float, list[tuple[float, float, float]]]]:
    """Pour chaque instant échantillonné : visages (centre x, centre y, largeur) en pixels source."""
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
        faces = [(cx / scale, cy / scale, w / scale) for cx, cy, w in detect(small)]
        # ignore les petits visages (public, arrière-plan)
        if faces:
            biggest = max(f[2] for f in faces)
            faces = [f for f in faces if f[2] >= 0.45 * biggest]
        out.append((t - start, faces))
        t += SAMPLE_EVERY
    cap.release()
    return out


def _median(values: list[float]) -> float:
    v = sorted(values)
    return v[len(v) // 2]


def _facecam(samples, src_w: int, src_h: int) -> tuple[int, int, int, int] | None:
    """Détecte une facecam (petit visage fixe, typique du gaming) ; renvoie sa zone x, y, w, h."""
    main = [max(f, key=lambda v: v[2]) for _, f in samples if f]
    if len(main) < 0.4 * len(samples):
        return None
    fw = _median([f[2] for f in main])
    cx, cy = _median([f[0] for f in main]), _median([f[1] for f in main])
    # Tolérances larges : mieux vaut reconnaître une facecam un peu grande ou qui bouge
    # que de basculer sur un cadrage « visage plein écran » qui perd le jeu.
    steady = sum(abs(f[0] - cx) < 0.07 * src_w and abs(f[1] - cy) < 0.07 * src_h for f in main)
    if fw > 0.22 * src_w or steady < 0.55 * len(main):
        return None  # visage occupant tout l'écran : ce n'est pas une facecam
    # Cadre autour du visage, au format du bandeau du haut (1080x700)
    w = min(fw * 4.0, src_w)  # pas trop serré : moins de zoom = image plus nette
    h = min(w * FACECAM_H / 1080, src_h)
    w = h * 1080 / FACECAM_H
    x = min(max(cx - w / 2, 0), src_w - w)
    y = min(max(cy - h * 0.45, 0), src_h - h)
    return int(x) // 2 * 2, int(y) // 2 * 2, int(w) // 2 * 2, int(h) // 2 * 2


COINS = {"hg": (0, 0), "hd": (1, 0), "bg": (0, 1), "bd": (1, 1)}


def _facecam_coin(samples, src_w: int, src_h: int, coin: str) -> tuple[int, int, int, int]:
    """Zone de la facecam quand l'utilisateur indique lui-même son coin.

    On cherche d'abord un visage dans ce quart de l'image ; si on n'en trouve pas,
    on prend une zone par défaut dans ce coin.
    """
    dx, dy = COINS[coin]
    dans_le_coin = []
    for _, faces in samples:
        for fx, fy, fw in faces:
            bon_x = (fx > src_w / 2) == bool(dx)
            bon_y = (fy > src_h / 2) == bool(dy)
            if bon_x and bon_y:
                dans_le_coin.append((fx, fy, fw))

    if len(dans_le_coin) >= max(3, 0.2 * len(samples)):
        cx = _median([f[0] for f in dans_le_coin])
        cy = _median([f[1] for f in dans_le_coin])
        fw = _median([f[2] for f in dans_le_coin])
        w = min(fw * 4.0, src_w)
    else:                                   # aucun visage repéré : zone par défaut
        w = src_w * 0.30
        cx = (src_w - w / 2) if dx else w / 2
        cy = (src_h * 0.72) if dy else (src_h * 0.28)

    h = min(w * FACECAM_H / 1080, src_h)
    w = h * 1080 / FACECAM_H
    x = min(max(cx - w / 2, 0), src_w - w)
    y = min(max(cy - h * 0.45, 0), src_h - h)
    return int(x) // 2 * 2, int(y) // 2 * 2, int(w) // 2 * 2, int(h) // 2 * 2


def analyze(src: Path, start: float, end: float, src_w: int, src_h: int, crop_w: int,
            allow_facecam: bool = True, coin: str = "auto") -> tuple[str, object]:
    """Choisit la mise en page : ("track", expr x(t)), ("facecam", zone) ou ("wide", None)."""
    try:
        samples = _scan(src, start, end)
    except Exception as exc:
        print(f"[reframe] analyse impossible ({exc})")
        return "wide", None
    if not samples:
        return "wide", None
    if allow_facecam and coin != "aucune":
        box = _facecam_coin(samples, src_w, src_h, coin) if coin in COINS \
            else _facecam(samples, src_w, src_h)
        if box:
            return "facecam", box
    expr = _track(samples, src_w, crop_w)
    return ("track", expr) if expr is not None else ("wide", None)


def _track(samples, src_w: int, crop_w: int) -> str | None:
    """Expression ffmpeg x(t) qui suit la personne, ou None si mieux vaut le plan large."""
    samples = [(t, [(f[0], f[2]) for f in faces]) for t, faces in samples]

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


# ------------------------------------------------- podcast : suivre la personne qui parle
PAROLE_FPS = 6           # images analysées par seconde (assez pour voir une bouche bouger)
PAROLE_FENETRE = 1.0     # on décide qui parle seconde par seconde
PAROLE_PLAN_MIN = 1.5    # jamais deux changements de plan à moins de 1,5 s
PAROLE_MARGE = 1.25      # le nouveau doit bouger 25 % de plus que l'actuel pour prendre la main


def _audio_actif(src: Path, start: float, end: float, pas: float) -> list[bool]:
    """Vrai quand quelqu'un parle (son au-dessus du bruit de fond), par tranche de `pas` s."""
    import subprocess

    import numpy as np

    sr = 8000
    brut = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start}", "-t", f"{end - start}",
                           "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                          capture_output=True).stdout
    a = np.frombuffer(brut, np.int16).astype(np.float32) / 32768
    n = int(sr * pas)
    if len(a) < n:
        return []
    rms = np.sqrt((a[: len(a) // n * n].reshape(-1, n) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    # 6 dB au-dessus du bruit de fond ; mais dans un podcast on parle presque tout le temps,
    # donc le « fond » peut être la voix elle-même : une voix normale (> -40 dB) passe toujours
    seuil = min(np.percentile(db, 20) + 6, -40)
    return (db > seuil).tolist()


def _personnes(detections: list[list[tuple]], src_w: int) -> list[float]:
    """Regroupe les visages par position horizontale : une place = une personne."""
    xs = sorted(f[0] for faces in detections for f in faces)
    if not xs:
        return []
    groupes: list[list[float]] = [[xs[0]]]
    for x in xs[1:]:
        if x - groupes[-1][-1] > 0.12 * src_w:
            groupes.append([])
        groupes[-1].append(x)
    n = len(detections)
    # une personne doit être là au moins 30 % du temps (sinon : passant, reflet, photo)
    return [_median(g) for g in groupes if len(g) >= 0.3 * n][:4]


def _coupures(images: list, seuil_min: float = 25.0) -> list[int]:
    """Indices où la caméra change (podcast déjà monté : gros plan → plan large…)."""
    import cv2
    import numpy as np

    diffs = [0.0]
    for (a, _), (b, _) in zip(images, images[1:]):
        pa, pb = cv2.resize(a, (64, 36)), cv2.resize(b, (64, 36))
        diffs.append(float(np.abs(pa.astype(np.int16) - pb.astype(np.int16)).mean()))
    med = float(np.median(diffs)) if diffs else 0.0
    return [i for i, d in enumerate(diffs) if d > max(seuil_min, 4 * med)]


def _parole_plan(detections, images, voix, src_w, debut, fin, x_avant):
    """Cadrage d'un plan (entre deux changements de caméra) : liste de (indice image, centre x)."""
    import numpy as np

    dets = detections[debut:fin]
    places = _personnes(dets, src_w)
    if not places:                         # personne de visible : on garde le cadre précédent
        return [(debut, x_avant)]
    if len(places) == 1:
        return [(debut, places[0])]

    n = fin - debut
    activite = np.full((len(places), n), np.nan)
    precedent: dict[int, np.ndarray] = {}
    import cv2
    for i in range(n):
        faces, (gris, scale) = dets[i], images[debut + i]
        vus = set()
        for cx, cy, w in faces:
            p = int(np.argmin([abs(cx - x) for x in places]))
            if abs(cx - places[p]) > 0.12 * src_w:
                continue
            # bas du visage : de la lèvre supérieure au menton
            x0, x1 = int((cx - 0.3 * w) * scale), int((cx + 0.3 * w) * scale)
            y0, y1 = int((cy + 0.15 * w) * scale), int((cy + 0.5 * w) * scale)
            zone = gris[max(y0, 0):max(y1, 1), max(x0, 0):max(x1, 1)]
            if zone.size < 20:
                continue
            zone = cv2.resize(zone, (32, 16)).astype(np.float32)
            if p in precedent:
                activite[p, i] = float(np.abs(zone - precedent[p]).mean())
            precedent[p] = zone
            vus.add(p)
        for p in list(precedent):          # personne pas vue sur cette image : on oublie
            if p not in vus:
                precedent.pop(p)

    # Chaque personne a sa « bouche au repos » (barbe, lumière) : on la retire
    for p in range(len(places)):
        ligne = activite[p][~np.isnan(activite[p])]
        if len(ligne):
            activite[p] -= np.median(ligne)

    par_fenetre = max(1, int(PAROLE_FENETRE * PAROLE_FPS))
    moyennes = np.array([np.nanmean(a) if (~np.isnan(a)).any() else -1e9 for a in activite])
    actuel = int(np.argmax(moyennes))
    keys = [(debut, places[actuel])]
    for k in range(0, n, par_fenetre):
        bloc = activite[:, k:k + par_fenetre]
        parle = voix[debut + k:debut + k + par_fenetre] if voix else [True]
        if not any(parle) or np.isnan(bloc).all():
            continue                        # silence ou visages cachés : on garde le plan
        score = np.array([np.nanmean(b) if (~np.isnan(b)).any() else -1e9 for b in bloc])
        meilleur = int(np.argmax(score))
        if (meilleur != actuel and score[meilleur] > 0
                and score[meilleur] > PAROLE_MARGE * max(score[actuel], 0) + 0.3
                and (debut + k - keys[-1][0]) / PAROLE_FPS >= PAROLE_PLAN_MIN):
            actuel = meilleur
            keys.append((debut + k, places[actuel]))
    return keys


def analyze_parole(src: Path, start: float, end: float, src_w: int, src_h: int,
                   crop_w: int) -> tuple[str, object]:
    """Cadrage serré sur la personne qui parle, avec un changement de plan net quand
    la parole passe à quelqu'un d'autre. Renvoie ("track", expression x(t)) ou ("wide", None).

    Méthode légère, sans modèle en plus : on repère les visages 6 fois par seconde, on
    mesure combien bouge le bas de chaque visage (la bouche) d'une image à l'autre, et
    pendant que le son indique une voix, celui dont la bouche bouge le plus parle.
    Les podcasts déjà montés changent de caméra (gros plan, plan large) : on repère ces
    changements et on décide plan par plan, pour ne jamais cadrer entre deux personnes.
    """
    import cv2

    try:
        detect = _get_detector()
        cap = cv2.VideoCapture(str(src))
        pas = 1.0 / PAROLE_FPS
        images, detections = [], []
        t = start
        while t < end:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                break
            scale = DETECT_WIDTH / frame.shape[1]
            small = cv2.resize(frame, None, fx=scale, fy=scale)
            gris = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            faces = [(cx / scale, cy / scale, w / scale) for cx, cy, w in detect(small)]
            if faces:
                grand = max(f[2] for f in faces)
                faces = [f for f in faces if f[2] >= 0.45 * grand]   # pas le public au fond
            images.append((gris, scale))
            detections.append(faces)
            t += pas
        cap.release()
    except Exception as exc:
        print(f"[reframe] suivi de la parole impossible ({exc})")
        return "wide", None
    if not any(detections):
        return "wide", None

    max_x = src_w - crop_w

    def to_x(c: float) -> int:
        return int(min(max(c - crop_w / 2, 0), max_x)) // 2 * 2

    voix = _audio_actif(src, start, end, pas)
    bornes = [0] + [i for i in _coupures(images) if i > 0] + [len(images)]
    premier = next(f for f in detections if f)
    x_courant = max(premier, key=lambda f: f[2])[0]
    keys: list[tuple[float, int]] = []
    for a, b in zip(bornes, bornes[1:]):
        if b - a < 2:
            continue
        for i, cx in _parole_plan(detections, images, voix, src_w, a, b, x_courant):
            x = to_x(cx)
            if not keys or x != keys[-1][1]:
                keys.append((round(i / PAROLE_FPS, 2), x))
            x_courant = cx
    if not keys:
        return "wide", None
    keys[0] = (0.0, keys[0][1])
    if len(keys) == 1:
        return "track", str(keys[0][1])
    # changements de plan nets (pas de glissement) : c'est le montage classique d'un podcast
    expr = str(keys[-1][1])
    for (t0, x0), (t1, _) in reversed(list(zip(keys, keys[1:]))):
        expr = f"if(lt(t,{t1:.2f}),{x0},{expr})"
    return "track", expr
