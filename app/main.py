"""Serveur web : API + interface."""
from __future__ import annotations

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

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
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

YOUTUBE = re.compile(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/", re.I)


class JobRequest(BaseModel):
    url: str
    num_clips: int = Field(5, ge=1, le=20)
    min_duration: int = Field(15, ge=5, le=120)
    max_duration: int = Field(40, ge=10, le=180)
    layout: str = Field("auto", pattern="^(auto|crop|blur)$")
    subtitles: bool = True
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
    try:
        info = pipeline.download(req["url"], work, _progress(job_id, "download"))
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
            )
            clips.append({**m, "file": name, "thumb": name.replace(".mp4", ".jpg"),
                          "duration": round(m["end"] - m["start"], 1)})
            _update(job_id, clips=clips)

        if os.getenv("KEEP_SOURCE", "0") != "1":
            info["path"].unlink(missing_ok=True)
        _update(job_id, status="done", progress=100, message=f"{len(clips)} shorts prêts !")
    except Exception as exc:
        traceback.print_exc()
        msg = str(exc).strip().splitlines()[-1] if str(exc).strip() else exc.__class__.__name__
        _update(job_id, status="error", message=f"Erreur : {msg}")


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
    return jobs[job_id]


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
