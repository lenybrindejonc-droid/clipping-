"""Serveur web : API + interface."""
from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import hashlib
import hmac
from urllib.parse import parse_qs

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import buffer_pub, lessons, pipeline, presets
from .highlights import find_moments
from .subtitles import SEUIL_CLIP, confiance

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("DATA_DIR", ROOT / "data")).resolve()
JOBS = DATA / "jobs"
JOBS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Clipping")
executor = ThreadPoolExecutor(max_workers=int(os.getenv("WORKERS", "1")))
lock = threading.Lock()
jobs: dict[str, dict] = {}
futures: dict[str, object] = {}
BUSY = ("download", "transcribe", "analyze", "render")

# ---------------------------------------------------------------- mot de passe (optionnel)

APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
AUTH_COOKIE = "clipping_auth"
MAX_TRIES, BAN_SECONDS = 8, 900   # 8 essais ratés → 15 minutes de blocage
_tries: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?"))


def _blocked(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _tries.get(ip, []) if now - t < BAN_SECONDS]
    _tries[ip] = recent
    return len(recent) >= MAX_TRIES


def _token() -> str:
    return hmac.new(APP_PASSWORD.encode(), b"clipping-session", hashlib.sha256).hexdigest()


LOGIN_PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Clipping — connexion</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0b10;color:#f2f2f7;
font:16px system-ui,sans-serif}form{background:#15151d;border:1px solid #262633;border-radius:16px;padding:24px;
width:min(340px,90vw);display:grid;gap:12px}input,button{font:inherit;padding:12px;border-radius:10px;border:1px solid #262633}
input{background:#0f0f15;color:#f2f2f7}button{background:#ff2e63;color:#fff;border:0;font-weight:700}
p{color:#ff7a8a;margin:0}</style></head><body><form method="post" action="/login">
<h2 style="margin:0">✂️ Clipping</h2>{error}<input type="password" name="password" placeholder="Mot de passe" autofocus required>
<button>Entrer</button></form></body></html>"""


@app.middleware("http")
async def require_password(request: Request, call_next):
    if not APP_PASSWORD:
        return await call_next(request)
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    if request.url.path == "/login" and request.method == "POST":
        ip = _client_ip(request)
        if _blocked(ip):
            return HTMLResponse(LOGIN_PAGE.replace(
                "{error}", "<p>Trop d'essais. Réessaie dans 15 minutes.</p>"), status_code=429)
        form = parse_qs((await request.body()).decode(errors="ignore"))
        given = (form.get("password") or [""])[0]
        if hmac.compare_digest(given.encode(), APP_PASSWORD.encode()):
            _tries.pop(ip, None)
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie(AUTH_COOKIE, _token(), max_age=30 * 86400, httponly=True,
                            secure=secure, samesite="none" if secure else "lax")
            return resp
        _tries.setdefault(ip, []).append(time.time())
        await asyncio.sleep(1)  # ralentit les essais au hasard
        return HTMLResponse(LOGIN_PAGE.replace("{error}", "<p>Mot de passe incorrect.</p>"), status_code=401)
    if hmac.compare_digest(request.cookies.get(AUTH_COOKIE, ""), _token()):
        return await call_next(request)
    if request.url.path.startswith(("/api/", "/media/")):
        return JSONResponse({"detail": "Connexion requise."}, status_code=401)
    return HTMLResponse(LOGIN_PAGE.replace("{error}", ""), status_code=401)


YOUTUBE = re.compile(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/", re.I)
TWITCH = re.compile(r"^https?://(www\.|m\.)?twitch\.tv/", re.I)

# Images à poser sur les clips (exigées par certaines campagnes). Celles de static/overlays
# font partie du site et survivent aux redémarrages ; celles envoyées depuis l'interface
# vont dans DATA/overlays et sont effacées quand Hugging Face redémarre.
OVERLAYS_SITE = ROOT / "static" / "overlays"
OVERLAYS_ENVOYES = DATA / "overlays"
OVERLAY_EXT = {".png", ".webp", ".jpg", ".jpeg"}
NOM_OVERLAY = r"^[\w.-]{0,80}$"


def _overlay_path(nom: str) -> Path | None:
    if not nom:
        return None
    for d in (OVERLAYS_ENVOYES, OVERLAYS_SITE):
        f = d / Path(nom).name
        if f.suffix.lower() in OVERLAY_EXT and f.is_file():
            return f
    return None


def _ajoute_mention(clip: dict, mention: str) -> dict:
    """Garantit la mention obligatoire (ex. twitch.tv/darealboeshi) dans chaque légende."""
    mention = mention.strip()
    if not mention:
        return clip
    def avec(texte: str) -> str:
        texte = (texte or "").rstrip()
        if mention.lower() in texte.lower():
            return texte
        return f"{texte}\n\n{mention}" if texte else mention
    caps = clip.get("captions") or {}
    clip["captions"] = {k: avec(v) for k, v in caps.items()} if caps else caps
    clip["description"] = avec(clip.get("description", ""))
    return clip


class JobRequest(BaseModel):
    url: str | None = None
    num_clips: int = Field(5, ge=1, le=30)
    min_duration: int = Field(15, ge=5, le=120)
    max_duration: int = Field(40, ge=10, le=180)
    layout: str = Field("auto", pattern="^(auto|crop|blur|gaming|parole)$")
    content_type: str = Field("auto", pattern="^(auto|gaming|podcast|vlog|tuto|humour|sport)$")
    facecam: str = Field("auto", pattern="^(auto|hg|hd|bg|bd|aucune)$")
    rules: str = Field("", max_length=4000)   # règles d'une campagne de clipping
    streamer: str = Field("", max_length=60)  # nom à placer dans les accroches
    jeu: str = Field("", max_length=60)       # nom du jeu
    mention: str = Field("", max_length=120)  # texte obligatoire dans chaque légende
    overlay: str = Field("", pattern=NOM_OVERLAY)  # image de campagne posée sur tout le clip
    overlay_pos: str = Field("bas", pattern="^(haut|milieu|bas)$")
    subtitles: bool = True
    show_hook: bool = False      # accroche incrustée sur la vidéo (sinon : texte à copier)
    zoom: bool = True            # zoom progressif sur le moment fort
    high_quality: bool = False
    language: str | None = None


def _save(job: dict) -> None:
    (JOBS / job["id"] / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2))


def _update(job_id: str, **fields) -> None:
    with lock:
        job = jobs[job_id]
        job.update(fields)
        job["updated_at"] = time.time()
        _save(job)


def _load_existing() -> None:
    for f in JOBS.glob("*/job.json"):
        try:
            job = json.loads(f.read_text())
        except Exception:
            continue
        if job["status"] not in ("done", "error"):
            job.update(status="error", message="Interrompu (redémarrage du serveur).")
        jobs[job["id"]] = job


_load_existing()

def _clean_sources(keep: str | None) -> None:
    """Libère le disque en supprimant les vidéos sources devenues inutiles.

    Une vidéo TÉLÉCHARGÉE peut être récupérée à tout moment : on la supprime sans risque.
    Une vidéo ENVOYÉE depuis l'ordinateur est irremplaçable : on garde les 2 plus récentes,
    pour que leurs clips restent modifiables.
    """
    if os.getenv("KEEP_SOURCE", "0") == "1":
        return
    envoyees = sorted((j for j in jobs.values() if not j["request"].get("url")),
                      key=lambda j: -j["created_at"])[:2]
    proteges = {keep} | {j["id"] for j in envoyees}
    for f in JOBS.glob("*/source*"):
        if f.parent.name not in proteges:
            f.unlink(missing_ok=True)


_done = [j for j in jobs.values() if j["status"] == "done"]
_clean_sources(max(_done, key=lambda j: j["created_at"])["id"] if _done else None)

# Pondération des étapes dans la barre de progression globale
STAGES = {"download": (0, 15), "transcribe": (15, 55), "analyze": (55, 65), "render": (65, 100)}


def _progress(job_id: str, stage: str):
    lo, hi = STAGES[stage]

    def cb(fraction: float, message: str) -> None:
        _update(job_id, status=stage, progress=round(lo + (hi - lo) * fraction, 1), message=message)

    return cb


def _pic_du_clip(energie: list[float], mouvement: list[float],
                 start: float, end: float) -> float | None:
    """Seconde la plus forte du clip (son + image), mesurée depuis son début."""
    import numpy as np

    i0, i1 = int(start), int(end)
    duree = end - start

    def normalise(valeurs):
        part = valeurs[i0:i1] if valeurs else []
        if len(part) < 3:
            return None
        a = np.array(part, dtype=float)
        etendue = a.max() - a.min()
        return (a - a.min()) / etendue if etendue > 1e-6 else None

    courbes = [c for c in (normalise(energie), normalise(mouvement)) if c is not None]
    if not courbes:
        return None
    n = min(len(c) for c in courbes)
    score = sum(c[:n] for c in courbes)
    pic = float(np.argmax(score)) + 0.5          # milieu de la seconde la plus forte
    if pic < 1.0 or pic > duree - 1.5:           # il faut la place pour la montée et le retour
        return None
    return round(pic, 2)


def _sous_titres_ok(req: dict, conf: float | None) -> bool:
    """Sous-titres seulement si la transcription du clip est assez sûre (sinon : aucun,
    plutôt qu'un texte absurde)."""
    return bool(req.get("subtitles", True)) and (conf is None or conf >= SEUIL_CLIP)


def _chrono(stage: str, t0: float) -> float:
    now = time.time()
    print(f"[durée] {stage} : {now - t0:.0f} s", flush=True)
    return now


def run_job(job_id: str) -> None:
    job = jobs[job_id]
    req = job["request"]
    work = JOBS / job_id
    _clean_sources(keep=job_id)
    ok = False
    t0 = time.time()
    _update(job_id, status="download", progress=1, message="Démarrage du téléchargement…")
    try:
        if req.get("overlay") and _overlay_path(req["overlay"]) is None:
            raise RuntimeError(f"l'image « {req['overlay']} » n'est plus sur le serveur "
                               "(effacée au redémarrage) : renvoie-la dans les réglages")
        if req.get("url"):
            info = pipeline.download(req["url"], work, _progress(job_id, "download"),
                                     req.get("high_quality", False))
        else:  # vidéo envoyée depuis l'ordinateur ou le téléphone
            path = next(work.glob("source.*"))
            info = {"path": path, "title": req.get("filename") or "Vidéo envoyée",
                    "duration": pipeline.check_video(path), "channel": ""}
        t0 = _chrono("téléchargement", t0)
        _update(job_id, title=info["title"], channel=info["channel"], duration=info["duration"])

        tr = pipeline.transcribe(info["path"], _progress(job_id, "transcribe"), req.get("language"),
                                 info["duration"], [req.get("streamer", ""), req.get("jeu", "")])
        t0 = _chrono("transcription", t0)
        (work / "transcript.json").write_text(json.dumps(tr, ensure_ascii=False))

        _progress(job_id, "analyze")(0, "Analyse du son (rires, cris, montées de ton)…")
        try:
            energie = pipeline.energy_profile(info["path"])
        except Exception as exc:
            print(f"[analyse] profil sonore indisponible ({exc})", flush=True)
            energie = []

        _progress(job_id, "analyze")(0.15, "Analyse de l'image (action, crashs, poursuites)…")
        try:
            mouvement = pipeline.motion_profile(info["path"])
        except Exception as exc:
            print(f"[analyse] profil d'image indisponible ({exc})", flush=True)
            mouvement = []
        t0 = _chrono("analyse son et image", t0)

        _progress(job_id, "analyze")(0.3, "L'IA cherche les moments les plus viraux…")
        moments, engine, note = find_moments(
            tr["segments"], info["title"], info["duration"],
            req["num_clips"], req["min_duration"], req["max_duration"], energie, mouvement,
            req.get("content_type", "auto"), req.get("rules", ""),
            req.get("streamer", ""), req.get("jeu", ""), req.get("mention", ""),
        )
        moments = [_ajoute_mention(m, req.get("mention", "")) for m in moments]
        t0 = _chrono("analyse IA", t0)
        if not moments:
            raise RuntimeError("Aucun moment exploitable trouvé (vidéo sans parole ?).")
        _update(job_id, engine=engine, engine_note=note)

        reglages = presets.get(req.get("content_type", "auto"))
        words = [w for s in tr["segments"] for w in s["words"]]
        clips = []
        render = _progress(job_id, "render")
        for i, m in enumerate(moments, 1):
            render((i - 1) / len(moments), f"Montage du clip {i}/{len(moments)}…")
            name = f"clip_{i:02d}.mp4"
            conf = confiance(words, m["start"], m["end"])
            m["confiance_sous_titres"] = conf
            pipeline.render_clip(
                info["path"], work / name, m["start"], m["end"], words,
                layout=req["layout"], subtitles=_sous_titres_ok(req, conf),
                hook=m.get("hook") if req.get("show_hook") else None,
                high_quality=req.get("high_quality", False),
                sub_style=reglages["sous_titres"], facecam=req.get("facecam", "auto"),
                zoom_at=(_pic_du_clip(energie, mouvement, m["start"], m["end"])
                         if reglages.get("zoom") and req.get("zoom", True) else None),
                overlay=_overlay_path(req.get("overlay", "")),
                overlay_pos=req.get("overlay_pos", "bas"),
            )
            clips.append({**m, "hook_on_video": m.get("hook") if req.get("show_hook") else "",
                          "file": name, "thumb": name.replace(".mp4", ".jpg"),
                          "duration": round(m["end"] - m["start"], 1), "layout": req["layout"],
                          "text": _clip_text(words, m["start"], m["end"]), "version": 1})
            _update(job_id, clips=clips)
            try:
                garder_automatiquement(job, clips[-1])
            except Exception as exc:
                print(f"[bibliothèque] clip non gardé ({exc})", flush=True)
            t0 = _chrono(f"montage clip {i}", t0)

        _update(job_id, status="done", progress=100, message=f"{len(clips)} shorts prêts !")
        ok = True
    except Exception as exc:
        traceback.print_exc()
        msg = str(exc).strip().splitlines()[-1] if str(exc).strip() else exc.__class__.__name__
        if "No space left" in str(exc) or "Errno 28" in str(exc):
            msg = "disque plein — libère de la place (commande : df -h ~)"
        _update(job_id, status="error", message=f"Erreur : {pipeline._strip(msg)}")
    finally:
        # En cas d'échec, supprime la vidéo source (sinon on la garde pour les modifications)
        if not ok and req.get("url") and os.getenv("KEEP_SOURCE", "0") != "1":
            for f in work.glob("source*"):
                f.unlink(missing_ok=True)
        for f in work.glob("*.ass"):
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------- modification d'un clip

def _words(work: Path) -> list[dict]:
    tr = json.loads((work / "transcript.json").read_text())
    return tr.get("words_edited") or [w for s in tr["segments"] for w in s["words"]]


def _clip_text(words: list[dict], start: float, end: float) -> str:
    return " ".join(w["word"] for w in words if w["end"] > start and w["start"] < end)


def _norm(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def _apply_text_edit(words: list[dict], start: float, end: float, text: str) -> list[dict]:
    """Remplace les mots de [start, end] par le texte corrigé, en gardant les horodatages
    des mots inchangés et en répartissant les nouveaux mots sur la durée des anciens."""
    inside = [w for w in words if w["end"] > start and w["start"] < end]
    outside = [w for w in words if not (w["end"] > start and w["start"] < end)]
    tokens: list[str] = []
    for tok in text.split():  # « ! », « ? », « , » seuls : collés au mot précédent
        if tokens and not re.search(r"\w", tok):
            tokens[-1] += tok
        else:
            tokens.append(tok)
    sm = difflib.SequenceMatcher(a=[_norm(w["word"]) for w in inside],
                                 b=[_norm(t) for t in tokens], autojunk=False)
    new: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            new += [{**inside[i1 + k], "word": tokens[j1 + k]} for k in range(i2 - i1)]
        elif tag in ("replace", "insert"):
            n = j2 - j1
            if i2 > i1:
                t0, t1 = inside[i1]["start"], inside[i2 - 1]["end"]
            else:
                t0 = inside[i1 - 1]["end"] if i1 > 0 else (inside[0]["start"] - 0.3 * n if inside else start)
                t1 = inside[i1]["start"] if i1 < len(inside) else t0 + 0.3 * n
                if not inside:
                    t0, t1 = start, end
            if t1 - t0 < 0.15 * n:
                t1 = t0 + 0.15 * n
            new += [{"start": round(t0 + (t1 - t0) * k / n, 2), "end": round(t0 + (t1 - t0) * (k + 1) / n, 2),
                     "word": tokens[j1 + k]} for k in range(n)]
    return sorted(outside + new, key=lambda w: w["start"])


class ClipEdit(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    hook: str = Field("", max_length=120)
    text: str | None = Field(None, max_length=5000)
    layout: str = Field("auto", pattern="^(auto|crop|blur|gaming|parole)$")
    content_type: str = Field("auto", pattern="^(auto|gaming|podcast|vlog|tuto|humour|sport)$")
    facecam: str = Field("auto", pattern="^(auto|hg|hd|bg|bd|aucune)$")
    rules: str = Field("", max_length=4000)   # règles d'une campagne de clipping
    streamer: str = Field("", max_length=60)  # nom à placer dans les accroches
    jeu: str = Field("", max_length=60)       # nom du jeu


def _set_clip(job_id: str, n: int, **fields) -> None:
    with lock:
        jobs[job_id]["clips"][n].update(fields)
        _save(jobs[job_id])


def rerender_clip(job_id: str, n: int, edit: dict) -> None:
    job = jobs[job_id]
    req = job["request"]
    work = JOBS / job_id
    clip = job["clips"][n]
    try:
        src = next((f for f in work.glob("source.*") if f.suffix in (".mp4", ".mkv", ".webm")), None)
        if src is None and not req.get("url"):
            raise RuntimeError(
                "la vidéo d'origine n'est plus sur le serveur (effacée au redémarrage du site, "
                "ou remplacée par des vidéos plus récentes). Renvoie le même fichier : "
                "les clips du nouveau projet seront modifiables")
        if src is None:
            _set_clip(job_id, n, rendering="Re-téléchargement de la vidéo…")
            _clean_sources(keep=job_id)
            src = pipeline.download(req["url"], work, lambda f, m: None,
                                    req.get("high_quality", False))["path"]
        _set_clip(job_id, n, rendering="Montage en cours…")

        words = _words(work)
        if edit["text"] is not None and edit["text"].strip() != _clip_text(words, clip["start"], clip["end"]).strip():
            # sous-titres corrigés à la main : on garde la correction pour les prochains montages
            words = _apply_text_edit(words, clip["start"], clip["end"], edit["text"])
            tr = json.loads((work / "transcript.json").read_text())
            tr["words_edited"] = words
            (work / "transcript.json").write_text(json.dumps(tr, ensure_ascii=False))

        start, end = edit["start"], edit["end"]
        conf = confiance(words, start, end)
        pipeline.render_clip(
            src, work / clip["file"], start, end, words, layout=edit["layout"],
            subtitles=_sous_titres_ok(req, conf), hook=edit["hook"].strip() or None,
            high_quality=req.get("high_quality", False), facecam=req.get("facecam", "auto"),
            overlay=_overlay_path(req.get("overlay", "")), overlay_pos=req.get("overlay_pos", "bas"),
        )
        _set_clip(job_id, n, start=round(start, 2), end=round(end, 2), duration=round(end - start, 1),
                  confiance_sous_titres=conf,
                  hook_on_video=edit["hook"].strip(), layout=edit["layout"],
                  text=_clip_text(words, start, end),
                  version=clip.get("version", 1) + 1, rendering=None, error=None)
    except Exception as exc:
        traceback.print_exc()
        _set_clip(job_id, n, rendering=None, error=pipeline._strip(str(exc).strip().splitlines()[-1]
                                                                    if str(exc).strip() else "erreur"))
    finally:
        for f in work.glob("*.ass"):
            f.unlink(missing_ok=True)


@app.post("/api/jobs/{job_id}/clips/{n}")
def edit_clip(job_id: str, n: int, edit: ClipEdit):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Projet introuvable.")
    ETAPES = {"queued": "en attente", "download": "téléchargement", "transcribe": "transcription",
              "analyze": "analyse", "render": "montage des clips"}
    if job["status"] in ETAPES:
        raise HTTPException(409, f"Le projet est encore en cours ({ETAPES[job['status']]}). "
                                 "Attends que tous les clips soient prêts pour en modifier un.")
    if job["status"] != "done" or not 0 <= n < len(job["clips"]):
        raise HTTPException(409, "Ce clip ne peut pas être modifié.")
    clip = job["clips"][n]
    if clip.get("rendering"):
        raise HTTPException(409, "Ce clip est déjà en cours de montage.")
    duration = job.get("duration") or 1e9
    start, end = max(0.0, edit.start), min(edit.end, duration)
    if end - start < 3:
        raise HTTPException(400, "Le clip doit durer au moins 3 secondes.")
    if end - start > 180:
        raise HTTPException(400, "Le clip ne peut pas dépasser 3 minutes.")
    _set_clip(job_id, n, rendering="En attente…", error=None)
    executor.submit(rerender_clip, job_id, n, edit.model_dump() | {"start": start, "end": end})
    return jobs[job_id]


def _new_job(req: JobRequest, extra: dict | None = None) -> dict:
    if req.min_duration >= req.max_duration:
        raise HTTPException(400, "La durée min doit être inférieure à la durée max.")
    job_id = uuid.uuid4().hex[:10]
    (JOBS / job_id).mkdir(parents=True)
    job = {
        "id": job_id, "request": req.model_dump() | (extra or {}),
        "status": "queued", "progress": 0, "message": "En file d'attente…",
        "title": extra.get("filename") if extra else None,
        "clips": [], "created_at": time.time(), "updated_at": time.time(),
    }
    with lock:
        jobs[job_id] = job
        _save(job)
    return job


@app.post("/api/jobs")
def create_job(req: JobRequest):
    if not req.url or not (YOUTUBE.match(req.url.strip()) or TWITCH.match(req.url.strip())):
        raise HTTPException(400, "Colle un lien YouTube ou Twitch valide.")
    if req.overlay and _overlay_path(req.overlay) is None:
        raise HTTPException(400, "L'image à incruster n'est plus sur le serveur : renvoie-la.")
    job = _new_job(req, {"url": req.url.strip()})
    futures[job["id"]] = executor.submit(run_job, job["id"])
    return job


LIMITES = {
    "num_clips": ("Nombre de clips", 1, 30),
    "min_duration": ("Durée minimum", 5, 120),
    "max_duration": ("Durée maximum", 10, 180),
}


def _explain_params(exc: ValidationError) -> str:
    """Message clair plutôt que « Paramètres invalides »."""
    for err in exc.errors():
        champ = err["loc"][0] if err["loc"] else ""
        if champ in LIMITES:
            nom, mini, maxi = LIMITES[champ]
            return f"{nom} : choisis une valeur entre {mini} et {maxi}."
        if champ == "layout":
            return "Cadrage invalide."
    return "Paramètres invalides."


VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}


def _drop_job(job_id: str) -> None:
    shutil.rmtree(JOBS / job_id, ignore_errors=True)
    with lock:
        jobs.pop(job_id, None)
        futures.pop(job_id, None)


UPLOADS = DATA / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_GB", "8")) * (1 << 30)


def _upload_dir(upload_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{16}", upload_id):
        raise HTTPException(404, "Envoi inconnu.")
    d = UPLOADS / upload_id
    if not d.is_dir():
        raise HTTPException(404, "Envoi inconnu ou expire : recommence.")
    return d


def _clean_uploads() -> None:
    """Supprime les envois abandonnes depuis plus de 24 h."""
    for d in UPLOADS.glob("*"):
        try:
            if d.is_dir() and time.time() - d.stat().st_mtime > 86400:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


_clean_uploads()


class UploadStart(BaseModel):
    filename: str = Field(max_length=300)
    size: int = Field(gt=0)
    params: JobRequest


@app.post("/api/uploads")
def start_upload(start: UploadStart):
    """Prepare un envoi par morceaux (reprise possible si la connexion coupe)."""
    ext = Path(Path(start.filename).name).suffix.lower()
    if ext not in VIDEO_EXT:
        raise HTTPException(400, f"Format non reconnu ({ext or 'sans extension'}). "
                                 "Envoie un fichier .mp4, .mkv, .webm ou .mov.")
    if start.size > MAX_UPLOAD:
        raise HTTPException(400, f"Fichier trop lourd ({start.size / (1 << 30):.1f} Go, "
                                 f"maximum {MAX_UPLOAD // (1 << 30)} Go). "
                                 "Decoupe-le en parties (script decouper.sh).")
    libre = shutil.disk_usage(DATA).free
    if libre < start.size * 1.6:
        raise HTTPException(507, "Pas assez d'espace sur le serveur "
                                 f"({libre / (1 << 30):.1f} Go libres). Envoie une video plus courte.")
    upload_id = uuid.uuid4().hex[:16]
    d = UPLOADS / upload_id
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({
        "filename": Path(start.filename).name, "ext": ext, "size": start.size,
        "params": start.params.model_dump(),
    }, ensure_ascii=False))
    (d / f"source{ext}").touch()
    return {"upload_id": upload_id, "received": 0, "chunk_size": 1 << 24}


@app.get("/api/uploads/{upload_id}")
def upload_state(upload_id: str):
    d = _upload_dir(upload_id)
    meta = json.loads((d / "meta.json").read_text())
    return {"upload_id": upload_id, "received": (d / f"source{meta['ext']}").stat().st_size,
            "size": meta["size"]}


@app.put("/api/uploads/{upload_id}")
async def upload_chunk(upload_id: str, request: Request, offset: int = 0):
    """Ajoute un morceau a la suite ; si l'offset ne correspond pas, renvoie la position reelle."""
    d = _upload_dir(upload_id)
    meta = json.loads((d / "meta.json").read_text())
    fichier = d / f"source{meta['ext']}"
    recu = fichier.stat().st_size
    if offset != recu:
        return JSONResponse({"received": recu, "detail": "position desynchronisee"}, status_code=409)
    try:
        with fichier.open("ab") as out:
            async for morceau in request.stream():
                if recu + len(morceau) > meta["size"]:
                    return JSONResponse({"received": recu,
                                         "detail": "plus de donnees que la taille annoncee"},
                                        status_code=400)
                out.write(morceau)
                recu += len(morceau)
    except Exception as exc:
        msg = "disque plein sur le serveur" if "space" in str(exc).lower() else "connexion interrompue"
        return JSONResponse({"received": fichier.stat().st_size, "detail": f"Morceau non recu ({msg})."},
                            status_code=500)
    d.touch()
    return {"received": fichier.stat().st_size, "size": meta["size"]}


@app.post("/api/uploads/{upload_id}/finish")
def finish_upload(upload_id: str):
    """Verifie le fichier complet, puis lance le traitement."""
    d = _upload_dir(upload_id)
    meta = json.loads((d / "meta.json").read_text())
    fichier = d / f"source{meta['ext']}"
    recu = fichier.stat().st_size
    if recu < meta["size"]:
        manquant = (meta["size"] - recu) / 1048576
        return JSONResponse({"received": recu,
                             "detail": f"Envoi incomplet : il manque {manquant:.0f} Mo."},
                            status_code=409)

    job = _new_job(JobRequest(**meta["params"]),
                   {"url": None, "filename": Path(meta["filename"]).stem[:120]})
    dest = JOBS / job["id"] / f"source{meta['ext']}"
    try:
        fichier.replace(dest)            # deplacement instantane (meme disque)
    except OSError:
        shutil.move(str(fichier), str(dest))
    shutil.rmtree(d, ignore_errors=True)

    try:
        pipeline.check_video(dest)
    except Exception as exc:
        _drop_job(job["id"])
        raise HTTPException(400, str(exc))
    futures[job["id"]] = executor.submit(run_job, job["id"])
    return job


@app.get("/api/overlays")
def lister_overlays():
    noms = set()
    for d in (OVERLAYS_SITE, OVERLAYS_ENVOYES):
        if d.is_dir():
            noms |= {f.name for f in d.iterdir() if f.suffix.lower() in OVERLAY_EXT}
    return sorted(noms)


@app.post("/api/overlays")
async def envoyer_overlay(request: Request, nom: str):
    nom = re.sub(r"[^\w.-]", "_", Path(nom).name)[:80]
    if Path(nom).suffix.lower() not in OVERLAY_EXT:
        raise HTTPException(400, "Envoie une image .png (transparente de préférence), .webp ou .jpg.")
    contenu = await request.body()
    if not contenu or len(contenu) > 15 * 1024 * 1024:
        raise HTTPException(400, "Image vide ou trop lourde (15 Mo maximum).")
    OVERLAYS_ENVOYES.mkdir(parents=True, exist_ok=True)
    dest = OVERLAYS_ENVOYES / nom
    dest.write_bytes(contenu)
    try:
        w, h = pipeline.probe_size(dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Ce fichier n'est pas une image lisible.")
    return {"nom": nom, "largeur": w, "hauteur": h, "plein_ecran": abs(w / h - 9 / 16) < 0.03}


class EnvoiBuffer(BaseModel):
    job_id: str | None = Field(None, pattern=r"^[0-9a-f]{10}$")
    n: int | None = Field(None, ge=0, le=100)
    cle: str | None = Field(None, pattern=r"^[0-9a-f]{12}$")   # clip de la bibliothèque
    chaines: list[str] = Field(default_factory=list, max_length=10)
    brouillon: bool = False   # test : le clip arrive en brouillon dans Buffer, rien n'est publié


_dernier_menage = 0.0


@app.get("/api/buffer")
def etat_buffer():
    """Buffer est-il réglé, et quelles chaînes TikTok / YouTube y sont connectées ?"""
    etat = buffer_pub.configure()
    if not etat["pret"]:
        return etat | {"chaines": []}
    try:
        return etat | {"chaines": buffer_pub.chaines()}
    except buffer_pub.ErreurEnvoi as exc:
        return {"pret": False, "manque": [], "erreur": str(exc), "chaines": []}


@app.post("/api/buffer/envoyer")
def envoyer_buffer(envoi: EnvoiBuffer):
    """Envoie UN clip (du projet ou de la bibliothèque) dans la file Buffer."""
    global _dernier_menage
    if not buffer_pub.configure()["pret"]:
        raise HTTPException(400, "Buffer n'est pas encore réglé sur le site (clés manquantes).")
    if envoi.cle:
        dossier = BIBLIO / envoi.cle
        meta = dossier / "meta.json"
        if not meta.exists():
            raise HTTPException(404, "Clip introuvable dans la bibliothèque.")
        clip, fichier, nom = json.loads(meta.read_text()), dossier / "clip.mp4", envoi.cle
    else:
        job = jobs.get(envoi.job_id or "")
        if not job or envoi.n is None or not 0 <= envoi.n < len(job["clips"]):
            raise HTTPException(404, "Clip introuvable.")
        if job["clips"][envoi.n].get("rendering"):
            raise HTTPException(409, "Ce clip est en cours de montage : attends qu'il soit prêt.")
        clip = job["clips"][envoi.n]
        fichier, nom = JOBS / job["id"] / clip["file"], f"{job['id']}_{envoi.n}_v{clip.get('version', 1)}"
    if not fichier.exists():
        raise HTTPException(410, "La vidéo a été effacée par le serveur : refais le clip.")
    if time.time() - _dernier_menage > 6 * 3600:      # place libérée sur Cloudinary
        _dernier_menage = time.time()
        buffer_pub.menage()
    try:
        resultats = buffer_pub.envoyer(fichier, nom, clip, envoi.chaines, envoi.brouillon)
    except buffer_pub.ErreurEnvoi as exc:
        raise HTTPException(502, str(exc))
    if any(r["ok"] for r in resultats) and not envoi.brouillon:
        marque = {"buffer_envoye": time.time()}
        if envoi.cle:
            meta.write_text(json.dumps(clip | marque, ensure_ascii=False, indent=1))
        else:
            _set_clip(envoi.job_id, envoi.n, **marque)
    return {"resultats": resultats}


@app.get("/api/jobs")
def list_jobs():
    return sorted(jobs.values(), key=lambda j: -j["created_at"])


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Projet introuvable.")
    job = jobs[job_id]
    if job["status"] == "queued":
        busy = next((j for j in jobs.values() if j["status"] in BUSY), None)
        job["message"] = (f"En attente : « {busy.get('title') or 'une autre vidéo'} » est en cours."
                          if busy else "Démarrage…")
    # Anciens projets : ajoute le texte des sous-titres de chaque clip (pour l'éditeur)
    if job["status"] == "done" and any("text" not in c for c in job["clips"]):
        try:
            words = _words(JOBS / job_id)
            for c in job["clips"]:
                c.setdefault("text", _clip_text(words, c["start"], c["end"]))
        except Exception:
            pass
    return job


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Projet introuvable.")
    if job["status"] == "queued":
        fut = futures.get(job_id)
        if fut is not None and not fut.cancel():
            raise HTTPException(409, "Ce projet vient de démarrer, impossible de l'annuler.")
    elif job["status"] in BUSY:
        raise HTTPException(409, "Projet en cours de traitement.")
    with lock:
        jobs.pop(job_id)
        futures.pop(job_id, None)
    shutil.rmtree(JOBS / job_id, ignore_errors=True)
    return {"ok": True}


class Avis(BaseModel):
    verdict: str = Field(pattern="^(bon|mauvais)$")
    raison: str = Field("", max_length=40)
    note: str = Field("", max_length=200)


@app.post("/api/jobs/{job_id}/clips/{n}/avis")
def noter_clip(job_id: str, n: int, avis: Avis):
    """Enregistre l'avis sur un clip : il servira aux analyses suivantes."""
    job = jobs.get(job_id)
    if not job or not 0 <= n < len(job["clips"]):
        raise HTTPException(404, "Clip introuvable.")
    clip = job["clips"][n]
    total = lessons.ajouter(avis.verdict, avis.raison, avis.note, {
        "titre": clip.get("title", "")[:80], "kind": clip.get("kind", ""),
        "duree": clip.get("duration"), "type_contenu": job["request"].get("content_type", "auto"),
    })
    _set_clip(job_id, n, avis=avis.verdict)
    return {"ok": True, "total_avis": total,
            "message": "Merci : l'IA en tiendra compte pour les prochaines vidéos."
                       if total >= 3 else
                       f"Noté ({total}/3 avis avant que l'IA commence à s'en servir)."}


@app.get("/api/presets")
def voir_presets():
    """Réglages conseillés par type de contenu (utilisés par la page)."""
    return {k: {"nom": v["nom"], "n": v["n"], "min_d": v["min_d"], "max_d": v["max_d"],
                "layout": v["layout"], "zoom": v.get("zoom", True)}
            for k, v in presets.PRESETS.items()}


@app.get("/api/lessons")
def voir_lessons():
    return {"resume": lessons.resume() or "Pas encore assez de retours."}


# ---------------------------------------------------------------- bibliothèque

BIBLIO = DATA / "bibliotheque"
BIBLIO.mkdir(parents=True, exist_ok=True)
GARDE_JOURS = int(os.getenv("GARDE_JOURS", "30"))


def _biblio_lire() -> list[dict]:
    entrees = []
    for meta in BIBLIO.glob("*/meta.json"):
        try:
            entrees.append(json.loads(meta.read_text()))
        except Exception:
            pass
    return sorted(entrees, key=lambda e: -e.get("ajoute_le", 0))


def _biblio_menage() -> None:
    """Supprime les clips gardés depuis plus de GARDE_JOURS jours."""
    limite = time.time() - GARDE_JOURS * 86400
    for entree in _biblio_lire():
        if entree.get("ajoute_le", 0) < limite:
            shutil.rmtree(BIBLIO / entree["id"], ignore_errors=True)


_biblio_menage()


class MarquePubliee(BaseModel):
    youtube_id: str = Field("", max_length=40)


def garder_automatiquement(job: dict, clip: dict) -> dict | None:
    """Range une copie du clip dans la bibliothèque, dès qu'il est monté.

    Aucune action de l'utilisateur : c'est un filet de sécurité. On utilise un lien
    matériel quand c'est possible, pour ne pas occuper le disque deux fois.
    """
    source = JOBS / job["id"] / clip["file"]
    if not source.exists():
        return None
    cle = uuid.uuid4().hex[:12]
    dossier = BIBLIO / cle
    dossier.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, dossier / "clip.mp4")
    except OSError:
        shutil.copy2(source, dossier / "clip.mp4")
    vignette = JOBS / job["id"] / clip.get("thumb", "")
    if vignette.exists():
        try:
            os.link(vignette, dossier / "thumb.jpg")
        except OSError:
            shutil.copy2(vignette, dossier / "thumb.jpg")

    entree = {k: clip.get(k) for k in ("title", "hook", "hooks", "description", "captions",
                                       "hashtags", "kind", "spoiler", "duration",
                                       "virality_score", "campaign_check")}
    entree |= {"id": cle, "projet": job.get("title") or job["id"], "ajoute_le": time.time(),
               "publie_le": None, "youtube_id": ""}
    (dossier / "meta.json").write_text(json.dumps(entree, ensure_ascii=False, indent=1))
    return entree


@app.post("/api/jobs/{job_id}/clips/{n}/garder")
def garder_clip(job_id: str, n: int):
    """Garde un clip à la demande (normalement déjà fait automatiquement)."""
    job = jobs.get(job_id)
    if not job or not 0 <= n < len(job["clips"]):
        raise HTTPException(404, "Clip introuvable.")
    clip = job["clips"][n]
    source = JOBS / job_id / clip["file"]
    if not source.exists():
        raise HTTPException(404, "Ce clip n'est plus sur le serveur.")

    cle = uuid.uuid4().hex[:12]
    dossier = BIBLIO / cle
    dossier.mkdir(parents=True)
    shutil.copy2(source, dossier / "clip.mp4")
    vignette = JOBS / job_id / clip.get("thumb", "")
    if vignette.exists():
        shutil.copy2(vignette, dossier / "thumb.jpg")

    entree = {k: clip.get(k) for k in ("title", "hook", "hooks", "description", "captions",
                                       "hashtags", "kind", "spoiler", "duration",
                                       "virality_score", "campaign_check")}
    entree |= {"id": cle, "projet": job.get("title") or job_id, "ajoute_le": time.time(),
               "publie_le": None, "youtube_id": ""}
    (dossier / "meta.json").write_text(json.dumps(entree, ensure_ascii=False, indent=1))
    _set_clip(job_id, n, garde=True)
    return entree


@app.get("/api/library")
def voir_bibliotheque():
    _biblio_menage()
    entrees = _biblio_lire()
    for e in entrees:
        if e.get("publie_le"):
            restant = GARDE_JOURS - (time.time() - e["publie_le"]) / 86400
            e["jours_restants"] = max(0, round(restant))
    return {"clips": entrees, "garde_jours": GARDE_JOURS}


@app.delete("/api/library/{cle}")
def supprimer_de_bibliotheque(cle: str):
    if not re.fullmatch(r"[0-9a-f]{12}", cle) or not (BIBLIO / cle).is_dir():
        raise HTTPException(404, "Clip introuvable dans la bibliothèque.")
    shutil.rmtree(BIBLIO / cle, ignore_errors=True)
    return {"ok": True}


@app.post("/api/library/{cle}/publie")
def marquer_publie(cle: str, marque: MarquePubliee):
    """Appelé par programmer.sh après un envoi réussi."""
    meta = BIBLIO / cle / "meta.json"
    if not re.fullmatch(r"[0-9a-f]{12}", cle) or not meta.exists():
        raise HTTPException(404, "Clip introuvable dans la bibliothèque.")
    entree = json.loads(meta.read_text())
    entree["publie_le"] = time.time()
    entree["youtube_id"] = marque.youtube_id
    meta.write_text(json.dumps(entree, ensure_ascii=False, indent=1))
    return entree


@app.get("/media/library/{cle}/{nom}")
def media_bibliotheque(cle: str, nom: str):
    if not re.fullmatch(r"[0-9a-f]{12}", cle) or nom not in ("clip.mp4", "thumb.jpg"):
        raise HTTPException(404)
    chemin = BIBLIO / cle / nom
    if not chemin.exists():
        raise HTTPException(404)
    return FileResponse(chemin)


@app.get("/api/library/zip")
def bibliotheque_zip(a_publier: bool = True):
    """Archive des clips de la bibliothèque, avec leurs textes."""
    import zipfile

    entrees = [e for e in _biblio_lire() if not (a_publier and e.get("publie_le"))]
    if not entrees:
        raise HTTPException(404, "Aucun clip à publier dans la bibliothèque.")
    archive = BIBLIO / "bibliotheque.zip"
    faux_projet = {"title": "Bibliothèque", "clips": []}
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as z:
        for e in entrees:
            nom = f"{e['id']}.mp4"
            z.write(BIBLIO / e["id"] / "clip.mp4", nom)
            faux_projet["clips"].append({**e, "file": nom})
        z.writestr("textes.md", _fiche_textes(faux_projet))
    return FileResponse(archive, filename="bibliotheque.zip", media_type="application/zip")


def _fiche_textes(job: dict) -> str:
    """Toutes les accroches et légendes dans un fichier texte : elles seraient perdues sinon."""
    lignes = [f"# {job.get('title') or 'Projet'}", ""]
    for i, c in enumerate(job["clips"], 1):
        lignes += [f"## Clip {i} — {c.get('title', '')}",
                   f"Durée : {c.get('duration')} s · score {c.get('virality_score')}/100"
                   + (f" · {c.get('kind')}" if c.get("kind") else "")
                   + (" · ⚠️ SPOILER" if c.get("spoiler") else ""),
                   f"Fichier : {c.get('file')}", ""]
        accroches = c.get("hooks") or ([{"texte": c["hook"], "pourquoi": ""}] if c.get("hook") else [])
        if accroches:
            lignes.append("Accroches proposées :")
            lignes += [f"  - {a['texte']}" + (f"   ({a['pourquoi']})" if a.get("pourquoi") else "")
                       for a in accroches]
            lignes.append("")
        legendes = c.get("captions") or {}
        if legendes:
            for plateforme, titre in (("tiktok", "TikTok"), ("youtube", "YouTube Shorts"), ("reels", "Reels")):
                if legendes.get(plateforme):
                    lignes += [f"Légende {titre} :", legendes[plateforme], ""]
        elif c.get("description"):
            lignes += ["Légende :", c["description"], ""]
        for v in c.get("campaign_check") or []:
            lignes.append(f"  [{v.get('verdict')}] {v.get('regle')} — {v.get('detail')}")
        lignes.append("")
    return "\n".join(lignes)


@app.get("/api/jobs/{job_id}/zip")
def telecharger_tout(job_id: str):
    """Tous les clips du projet + leurs textes, dans un seul fichier."""
    import zipfile

    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Projet introuvable.")
    fichiers = [(JOBS / job_id / c["file"]) for c in job["clips"]]
    fichiers = [f for f in fichiers if f.exists()]
    if not fichiers:
        raise HTTPException(404, "Aucun clip disponible : ils ont été effacés par le serveur.")

    nom = re.sub(r"[^\w -]", "", (job.get("title") or "clips"))[:50].strip() or "clips"
    archive = JOBS / job_id / "tous_les_clips.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as z:   # vidéos déjà compressées
        for f in fichiers:
            z.write(f, f.name)
        z.writestr("textes.md", _fiche_textes(job))
    return FileResponse(archive, filename=f"{nom}.zip", media_type="application/zip")


@app.get("/media/{job_id}/{name}")
def media(job_id: str, name: str):
    if not re.fullmatch(r"[0-9a-f]{10}", job_id) or not re.fullmatch(r"clip_\d{2}\.(mp4|jpg)", name):
        raise HTTPException(404)
    path = JOBS / job_id / name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
