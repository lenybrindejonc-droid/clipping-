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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import pipeline
from .highlights import find_moments

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("DATA_DIR", ROOT / "data")).resolve()
JOBS = DATA / "jobs"
JOBS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Clipping")
executor = ThreadPoolExecutor(max_workers=int(os.getenv("WORKERS", "1")))
lock = threading.Lock()
jobs: dict[str, dict] = {}

# ---------------------------------------------------------------- mot de passe (optionnel)

APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
AUTH_COOKIE = "clipping_auth"


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
        form = parse_qs((await request.body()).decode(errors="ignore"))
        given = (form.get("password") or [""])[0]
        if hmac.compare_digest(given.encode(), APP_PASSWORD.encode()):
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie(AUTH_COOKIE, _token(), max_age=30 * 86400, httponly=True,
                            secure=secure, samesite="none" if secure else "lax")
            return resp
        await asyncio.sleep(1)  # ralentit les essais au hasard
        return HTMLResponse(LOGIN_PAGE.replace("{error}", "<p>Mot de passe incorrect.</p>"), status_code=401)
    if hmac.compare_digest(request.cookies.get(AUTH_COOKIE, ""), _token()):
        return await call_next(request)
    if request.url.path.startswith(("/api/", "/media/")):
        return JSONResponse({"detail": "Connexion requise."}, status_code=401)
    return HTMLResponse(LOGIN_PAGE.replace("{error}", ""), status_code=401)


YOUTUBE = re.compile(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/", re.I)


class JobRequest(BaseModel):
    url: str
    num_clips: int = Field(5, ge=1, le=20)
    min_duration: int = Field(15, ge=5, le=120)
    max_duration: int = Field(40, ge=10, le=180)
    layout: str = Field("auto", pattern="^(auto|crop|blur|gaming)$")
    subtitles: bool = True
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
    """Garde la vidéo source d'un seul projet (pour pouvoir modifier ses clips) : le disque est petit."""
    if os.getenv("KEEP_SOURCE", "0") == "1":
        return
    for f in JOBS.glob("*/source*"):
        if f.parent.name != keep:
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


def run_job(job_id: str) -> None:
    job = jobs[job_id]
    req = job["request"]
    work = JOBS / job_id
    _clean_sources(keep=job_id)
    ok = False
    try:
        info = pipeline.download(req["url"], work, _progress(job_id, "download"),
                                 req.get("high_quality", False))
        _update(job_id, title=info["title"], channel=info["channel"], duration=info["duration"])

        tr = pipeline.transcribe(info["path"], _progress(job_id, "transcribe"), req.get("language"),
                                 info["duration"])
        (work / "transcript.json").write_text(json.dumps(tr, ensure_ascii=False))

        _progress(job_id, "analyze")(0, "L'IA cherche les moments les plus viraux…")
        moments, engine, note = find_moments(
            tr["segments"], info["title"], info["duration"],
            req["num_clips"], req["min_duration"], req["max_duration"],
        )
        if not moments:
            raise RuntimeError("Aucun moment exploitable trouvé (vidéo sans parole ?).")
        _update(job_id, engine=engine, engine_note=note)

        words = [w for s in tr["segments"] for w in s["words"]]
        clips = []
        render = _progress(job_id, "render")
        for i, m in enumerate(moments, 1):
            render((i - 1) / len(moments), f"Montage du clip {i}/{len(moments)}…")
            name = f"clip_{i:02d}.mp4"
            pipeline.render_clip(
                info["path"], work / name, m["start"], m["end"], words,
                layout=req["layout"], subtitles=req["subtitles"], hook=m.get("hook"),
                high_quality=req.get("high_quality", False),
            )
            clips.append({**m, "file": name, "thumb": name.replace(".mp4", ".jpg"),
                          "duration": round(m["end"] - m["start"], 1), "layout": req["layout"],
                          "text": _clip_text(words, m["start"], m["end"]), "version": 1})
            _update(job_id, clips=clips)

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
        if not ok and os.getenv("KEEP_SOURCE", "0") != "1":
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
    layout: str = Field("auto", pattern="^(auto|crop|blur|gaming)$")


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
        if src is None:
            _set_clip(job_id, n, rendering="Re-téléchargement de la vidéo…")
            _clean_sources(keep=job_id)
            src = pipeline.download(req["url"], work, lambda f, m: None,
                                    req.get("high_quality", False))["path"]
        _set_clip(job_id, n, rendering="Montage en cours…")

        words = _words(work)
        if edit["text"] is not None and edit["text"].strip() != _clip_text(words, clip["start"], clip["end"]).strip():
            words = _apply_text_edit(words, clip["start"], clip["end"], edit["text"])
            tr = json.loads((work / "transcript.json").read_text())
            tr["words_edited"] = words
            (work / "transcript.json").write_text(json.dumps(tr, ensure_ascii=False))

        start, end = edit["start"], edit["end"]
        pipeline.render_clip(
            src, work / clip["file"], start, end, words, layout=edit["layout"],
            subtitles=req["subtitles"], hook=edit["hook"].strip() or None,
            high_quality=req.get("high_quality", False),
        )
        _set_clip(job_id, n, start=round(start, 2), end=round(end, 2), duration=round(end - start, 1),
                  hook=edit["hook"].strip(), layout=edit["layout"], text=_clip_text(words, start, end),
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
    if job["status"] != "done" or not 0 <= n < len(job["clips"]):
        raise HTTPException(409, "Ce clip ne peut pas être modifié pour l'instant.")
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


@app.post("/api/jobs")
def create_job(req: JobRequest):
    if not YOUTUBE.match(req.url.strip()):
        raise HTTPException(400, "Colle un lien YouTube valide.")
    if req.min_duration >= req.max_duration:
        raise HTTPException(400, "La durée min doit être inférieure à la durée max.")
    job_id = uuid.uuid4().hex[:10]
    (JOBS / job_id).mkdir(parents=True)
    job = {
        "id": job_id, "request": req.model_dump() | {"url": req.url.strip()},
        "status": "queued", "progress": 0, "message": "En file d'attente…",
        "title": None, "clips": [], "created_at": time.time(), "updated_at": time.time(),
    }
    with lock:
        jobs[job_id] = job
        _save(job)
    executor.submit(run_job, job_id)
    return job


@app.get("/api/jobs")
def list_jobs():
    return sorted(jobs.values(), key=lambda j: -j["created_at"])


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Projet introuvable.")
    job = jobs[job_id]
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
    if job["status"] not in ("done", "error"):
        raise HTTPException(409, "Projet en cours de traitement.")
    with lock:
        jobs.pop(job_id)
    shutil.rmtree(JOBS / job_id, ignore_errors=True)
    return {"ok": True}


@app.get("/media/{job_id}/{name}")
def media(job_id: str, name: str):
    if not re.fullmatch(r"[0-9a-f]{10}", job_id) or not re.fullmatch(r"clip_\d{2}\.(mp4|jpg)", name):
        raise HTTPException(404)
    path = JOBS / job_id / name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
