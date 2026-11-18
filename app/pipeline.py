"""Étapes techniques : téléchargement, transcription, rendu vertical."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

from .reframe import crop_x_expression
from .subtitles import write_ass

Progress = Callable[[float, str], None]

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
OUT_W, OUT_H = 1080, 1920

_whisper = None


def download(url: str, workdir: Path, progress: Progress) -> dict:
    """Télécharge la vidéo YouTube (≤1080p) en mp4."""
    import yt_dlp

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                progress(d.get("downloaded_bytes", 0) / total, "Téléchargement de la vidéo…")

    opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(workdir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
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


def transcribe(path: Path, progress: Progress, language: str | None = None) -> dict:
    """Transcription Whisper locale avec horodatage au mot près."""
    global _whisper
    from faster_whisper import WhisperModel

    if _whisper is None:
        progress(0.0, f"Chargement du modèle Whisper ({WHISPER_MODEL})…")
        _whisper = WhisperModel(WHISPER_MODEL, device="auto", compute_type="int8")

    seg_iter, info = _whisper.transcribe(
        load_audio(path), word_timestamps=True, vad_filter=True, language=language or None
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
            progress(min(s.end / info.duration, 1.0), "Transcription de l'audio…")
    return {"language": info.language, "segments": segments}


def render_clip(
    src: Path,
    out: Path,
    start: float,
    end: float,
    words: list[dict],
    layout: str = "crop",
    subtitles: bool = True,
    hook: str | None = None,
) -> None:
    """Découpe [start, end], recadre en 9:16 et incruste les sous-titres."""
    duration = end - start
    src_w, src_h = probe_size(src)
    filters: list[str] = []

    if layout == "crop" and src_w / src_h > OUT_W / OUT_H:
        crop_w = int(src_h * OUT_W / OUT_H) // 2 * 2
        x_expr = crop_x_expression(src, start, end, src_w, src_h, crop_w)
        base = f"[0:v]crop=w={crop_w}:h={src_h}:x='{x_expr}':y=0,scale={OUT_W}:{OUT_H},setsar=1"
    else:
        # Fond flou + vidéo entière centrée
        base = (
            f"[0:v]split[a][b];"
            f"[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},"
            f"boxblur=25:5,eq=brightness=-0.08[bg];"
            f"[b]scale={OUT_W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1"
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
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
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
