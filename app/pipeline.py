"""Étapes techniques : téléchargement, transcription, rendu vertical."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading
import time
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


def _cookie_file() -> str | None:
    """Cookies YouTube (fichier cookies.txt ou secret YT_COOKIES) : aident quand YouTube
    bloque les serveurs (« Sign in to confirm you're not a bot »)."""
    content = os.getenv("YT_COOKIES", "").replace("\\n", "\n").strip()
    if content:
        path = Path(os.getenv("DATA_DIR", "data")) / "cookies.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(content + "\n")
            path.chmod(0o600)
        return str(path)
    local = Path(__file__).resolve().parent.parent / "cookies.txt"
    return str(local) if local.exists() else None


# Les « clients » que yt-dlp imite. Depuis un serveur, YouTube coupe souvent le client « web » :
# on essaie plusieurs identités avant d'abandonner.
PLAYER_CLIENTS = [c.strip() for c in os.getenv("YT_PLAYER_CLIENTS", "tv,ios,web_safari,android").split(",") if c.strip()]
YTDLP_CMD = shlex.split(os.getenv("YTDLP_CMD", "")) or [sys.executable, "-m", "yt_dlp"]
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "1200"))  # 20 minutes maximum
NETWORK_ERRORS = ("TIMEOUT", "UNEXPECTED_EOF", "SSLError", "Unable to download API page", "Remote end closed",
                  "Connection reset", "timed out", "Failed to extract any player response")


def download(url: str, workdir: Path, progress: Progress, high_quality: bool = False) -> dict:
    """Télécharge la vidéo YouTube (≤1080p) en mp4.

    yt-dlp tourne dans un processus séparé : on peut donc l'arrêter net s'il dépasse
    DOWNLOAD_TIMEOUT, au lieu de bloquer le site pour toujours.
    """
    formats = [
        "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/b[vcodec^=avc1][height<=1080]",
        "b[ext=mp4][height<=1080]/18/b",
    ]
    if high_quality:
        formats.insert(0, "bv*[vcodec^=vp09][height<=1440][height>1080]+ba/"
                          "bv*[vcodec^=vp9][height<=1440][height>1080]+ba")

    deadline = time.monotonic() + DOWNLOAD_TIMEOUT
    last_err = ""
    for fmt in formats:
        for f in workdir.glob("source.*"):
            f.unlink()
        remaining = deadline - time.monotonic()
        if remaining < 30:
            raise RuntimeError(f"téléchargement trop long (plus de {max(1, DOWNLOAD_TIMEOUT // 60)} minutes) "
                               "— YouTube ne répond pas correctement depuis ce serveur")
        info, err = _run_ytdlp(url, workdir, fmt, progress, remaining)
        if info:
            path = next(workdir.glob("source.*"))
            return {
                "path": path,
                "title": info.get("title") or "Vidéo",
                "duration": float(info.get("duration") or probe_duration(path)),
                "channel": info.get("channel") or info.get("uploader") or "",
            }
        last_err = err
        print(f"[download] échec avec le format {fmt!r} : {err[:400]}", flush=True)
        if "Sign in" in err or "not a bot" in err:
            raise RuntimeError("YouTube bloque le téléchargement depuis ce serveur. Ajoute des "
                               "cookies YouTube (voir README, section « YouTube bloque »)")
        if "Private video" in err or "Video unavailable" in err or "members-only" in err:
            raise RuntimeError(f"vidéo inaccessible ({_strip(err.splitlines()[-1] if err else '')})")

    if any(e in last_err for e in NETWORK_ERRORS):
        raise RuntimeError("YouTube refuse la connexion depuis ce serveur (connexion coupée). "
                           "Solution : des cookies YouTube d'un compte secondaire — voir README, "
                           "section « YouTube bloque »")
    raise RuntimeError(f"téléchargement impossible ({_strip(last_err.splitlines()[-1] if last_err else '')})")


def _run_ytdlp(url: str, workdir: Path, fmt: str, progress: Progress,
               timeout: float) -> tuple[dict | None, str]:
    """Lance yt-dlp. Renvoie (infos, "") si ça marche, (None, erreur) sinon."""
    cmd = [*YTDLP_CMD,
           "-f", fmt, "--merge-output-format", "mp4",
           "-o", str(workdir / "source.%(ext)s"),
           "--no-playlist", "--no-color", "--newline", "--no-warnings",
           "--progress-template", "PCT:%(progress._percent_str)s",
           "--print-json", "--no-simulate",
           "--socket-timeout", "20", "--retries", "3", "--fragment-retries", "5",
           "--extractor-retries", "2",
           "--extractor-args", f"youtube:player_client={','.join(PLAYER_CLIENTS)}",
           # solveur des défis JavaScript de YouTube (sans lui : « No video formats found »)
           "--remote-components", "ejs:github"]
    if os.getenv("YT_FORCE_IPV4", "1") == "1":
        cmd.append("--force-ipv4")
    if cookies := _cookie_file():
        cmd += ["--cookies", cookies]
    cmd.append(url)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace", bufsize=1)
    info: dict | None = None
    killed = False

    def watchdog() -> None:
        nonlocal killed
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            killed = True
            proc.kill()

    timer = threading.Thread(target=watchdog, daemon=True)
    timer.start()
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("PCT:"):
            try:
                progress(min(float(line[4:].strip().rstrip("%")) / 100, 1.0),
                         "Téléchargement de la vidéo…")
            except ValueError:
                pass
        elif line.startswith("{"):
            try:
                info = json.loads(line)
            except json.JSONDecodeError:
                pass
    err = proc.stderr.read()
    proc.wait()
    if killed:
        return None, f"TIMEOUT: arrêté après {timeout / 60:.0f} minutes"
    if proc.returncode != 0 or info is None:
        return None, err or f"yt-dlp s'est arrêté (code {proc.returncode})"
    return info, ""


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
    high_quality: bool = False,
) -> None:
    """Découpe [start, end], recadre en 9:16 et incruste les sous-titres."""
    duration = end - start
    src_w, src_h = probe_size(src)
    filters: list[str] = []

    crop_w = int(src_h * OUT_W / OUT_H) // 2 * 2
    mode, data = "wide", None
    if layout != "blur" and src_w / src_h > OUT_W / OUT_H:
        mode, data = reframe.analyze(src, start, end, src_w, src_h, crop_w,
                                     allow_facecam=layout in ("auto", "gaming"))
        if mode == "wide" and layout in ("crop", "gaming"):
            mode, data = "track", str((src_w - crop_w) // 2)  # recadrage centré forcé

    sharpen = "unsharp=5:5:0.6:5:5:0"
    sub_pos = hook_pos = None
    if mode == "facecam":
        # Écran partagé : facecam en haut, jeu (centre de l'image) en bas
        fx, fy, fw, fh = data
        top_h = reframe.FACECAM_H
        bot_h = OUT_H - top_h
        gw = int(src_h * OUT_W / bot_h) // 2 * 2
        gx = (src_w - gw) // 2
        base = (
            f"[0:v]split[a][b];"
            f"[a]crop={fw}:{fh}:{fx}:{fy},hqdn3d=1.5:1.5:3:3,scale={OUT_W}:{top_h}:flags=lanczos,"
            f"unsharp=5:5:1.0:5:5:0.0[top];"
            f"[b]crop={gw}:{src_h}:{gx}:0,scale={OUT_W}:{bot_h}:flags=lanczos,{sharpen}[bot];"
            f"[top][bot]vstack,setsar=1"
        )
        sub_pos = (OUT_W // 2, top_h)            # sous-titres sur la jonction
        hook_pos = (OUT_W // 2, OUT_H - 260)     # accroche en bas, sur le jeu
    elif mode == "track":
        base = (f"[0:v]crop=w={crop_w}:h={src_h}:x='{data}':y=0,"
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
        write_ass(ass, words if subtitles else [], start, end, OUT_W, OUT_H, hook=hook,
                  sub_pos=sub_pos, hook_pos=hook_pos)
        filters.append(f"ass={ass.name}")

    vf = ",".join(filters) + "[v]"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src.resolve()),
        "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", X264_PRESET, "-threads", "0", "-crf", "18" if high_quality else "20", "-pix_fmt", "yuv420p",
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
