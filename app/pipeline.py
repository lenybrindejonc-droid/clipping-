"""Étapes techniques : téléchargement, transcription, rendu vertical."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

from . import reframe
from .subtitles import write_ass

Progress = Callable[[float, str], None]

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
OUT_W, OUT_H = 1080, 1920
# Petits processeurs (≤ 2 cœurs) : encodage plus rapide, fichier un peu plus gros
X264_PRESET = os.getenv("X264_PRESET") or ("superfast" if (os.cpu_count() or 4) <= 2 else "veryfast")

_whisper = None


def _strip(text: str) -> str:
    """Retire les codes couleur du terminal des messages d'erreur."""
    import re
    return re.sub(r"\x1b\[[0-9;]*m|\[[0-9;]*m", "", text).replace("ERROR:", "").strip()


def download(url: str, workdir: Path, progress: Progress) -> dict:
    """Télécharge la vidéo YouTube (≤1080p) en mp4."""
    import yt_dlp

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                progress(d.get("downloaded_bytes", 0) / total, "Téléchargement de la vidéo…")

    # Ordre de préférence : H.264 (décodage léger, même sur petit PC), puis fichier unique sans
    # fusion (si la fusion ffmpeg échoue), puis n'importe quoi.
    formats = [
        "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/b[vcodec^=avc1][height<=1080]",
        "b[ext=mp4][height<=1080]/18/b",
    ]
    last_exc: Exception | None = None
    for fmt in formats:
        for f in workdir.glob("source.*"):
            f.unlink()
        opts = {
            "format": fmt,
            "merge_output_format": "mp4",
            "outtmpl": str(workdir / "source.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "no_color": True,
            "progress_hooks": [hook],
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            break
        except yt_dlp.utils.DownloadError as exc:
            last_exc = exc
            print(f"[download] échec avec le format {fmt!r} : {exc}")
            if "Sign in" in str(exc) or "Private video" in str(exc) or "unavailable" in str(exc):
                raise
    else:
        raise RuntimeError(f"téléchargement impossible ({_strip(str(last_exc))}). "
                           "Vérifie l'espace disque libre (commande : df -h ~)")
    path = next(workdir.glob("source.*"))
    return {
        "path": path,
        "title": info.get("title") or "Vidéo",
        "duration": float(info.get("duration") or probe_duration(path)),
        "channel": info.get("channel") or info.get("uploader") or "",
    }


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def probe_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True, check=True,
    )
    w, h = out.stdout.strip().split("x")[:2]
    return int(w), int(h)


def load_audio(path: Path):
    """Décode l'audio en mono 16 kHz avec ffmpeg (évite PyAV, incompatible en v15+)."""
    import numpy as np

    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path),
         "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True, check=True,
    )
    return np.frombuffer(out.stdout, np.int16).astype(np.float32) / 32768.0


def transcribe(path: Path, progress: Progress, language: str | None = None,
               duration: float | None = None) -> dict:
    """Transcription en ligne (Groq) si une clé est configurée, sinon locale."""
    from . import cloud_transcribe

    if cloud_transcribe.available():
        try:
            return cloud_transcribe.transcribe(path, duration or probe_duration(path), progress, language)
        except Exception as exc:
            print(f"[transcribe] Groq indisponible : {exc}")
            if os.getenv("TRANSCRIBE_FALLBACK", "0") != "1":
                # Pas de repli silencieux : en local, ça peut prendre des heures sur un petit PC
                raise RuntimeError(f"transcription en ligne (Groq) impossible : {exc}") from exc
            progress(0.0, f"Groq impossible ({exc}) → transcription locale (lente)…")
    return transcribe_local(path, progress, language)


def transcribe_local(path: Path, progress: Progress, language: str | None = None) -> dict:
    """Transcription Whisper locale avec horodatage au mot près."""
    global _whisper
    from faster_whisper import WhisperModel

    if _whisper is None:
        progress(0.0, f"Chargement du modèle Whisper ({WHISPER_MODEL})…")
        _whisper = WhisperModel(WHISPER_MODEL, device="auto", compute_type="int8",
                                cpu_threads=os.cpu_count() or 4)

    seg_iter, info = _whisper.transcribe(
        load_audio(path), word_timestamps=True, vad_filter=True,
        beam_size=1, condition_on_previous_text=False,  # ~2x plus rapide, qualité quasi identique
        language=language or None
    )
    segments = []
    for s in seg_iter:
        segments.append({
            "start": round(s.start, 2),
            "end": round(s.end, 2),
            "text": s.text.strip(),
            "words": [
                {"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()}
                for w in (s.words or []) if w.word.strip()
            ],
        })
        if info.duration:
            progress(min(s.end / info.duration, 1.0),
                     "Transcription locale (lente — ajoute une clé GROQ_API_KEY pour aller 50x plus vite)…")
    return {"language": info.language, "segments": segments}


def render_clip(
    src: Path,
    out: Path,
    start: float,
    end: float,
    words: list[dict],
    layout: str = "auto",
    subtitles: bool = True,
    hook: str | None = None,
) -> None:
    """Découpe [start, end], recadre en 9:16 et incruste les sous-titres."""
    duration = end - start
    src_w, src_h = probe_size(src)
    filters: list[str] = []

    x_expr = None
    crop_w = int(src_h * OUT_W / OUT_H) // 2 * 2
    if layout in ("auto", "crop") and src_w / src_h > OUT_W / OUT_H:
        x_expr = reframe.plan(src, start, end, src_w, crop_w)
        if x_expr is None and layout == "crop":
            x_expr = str((src_w - crop_w) // 2)  # recadrage centré forcé

    sharpen = "unsharp=5:5:0.6:5:5:0"
    if x_expr is not None:
        base = (f"[0:v]crop=w={crop_w}:h={src_h}:x='{x_expr}':y=0,"
                f"scale={OUT_W}:{OUT_H}:flags=lanczos,{sharpen},setsar=1")
    else:
        # Vidéo entière centrée (zoomée) sur fond flou — flou calculé en petit = rapide
        base = (
            f"[0:v]split[a][b];"
            f"[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
            f"boxblur=12:3,eq=brightness=-0.1,scale={OUT_W}:{OUT_H}[bg];"
            f"[b]scale={OUT_W}*1.15:-2:flags=lanczos,crop={OUT_W}:ih,{sharpen}[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2-80,setsar=1"
        )
    filters.append(base)

    if (subtitles and words) or hook:
        ass = out.with_suffix(".ass")
        write_ass(ass, words if subtitles else [], start, end, OUT_W, OUT_H, hook=hook)
        filters.append(f"ass={ass.name}")

    vf = ",".join(filters) + "[v]"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src.resolve()),
        "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", X264_PRESET, "-threads", "0", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
        out.name,
    ]
    subprocess.run(cmd, cwd=out.parent, check=True, capture_output=True, text=True)

    # Miniature
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{min(1.0, duration / 2):.2f}", "-i", out.name,
         "-frames:v", "1", "-vf", "scale=360:-2", out.with_suffix(".jpg").name],
        cwd=out.parent, check=False, capture_output=True,
    )
