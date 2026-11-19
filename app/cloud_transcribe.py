"""Transcription en ligne via Groq (Whisper large v3 turbo) — rapide même sur un petit PC.

Clé gratuite : https://console.groq.com/keys  →  GROQ_API_KEY dans .env
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
CHUNK = 600  # secondes par morceau (reste bien sous la limite de 25 Mo)


def available() -> bool:
    return bool(os.getenv("GROQ_API_KEY", "").strip())


def _encode(src: Path, dst: Path, start: float, dur: float) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-ss", f"{start}", "-t", f"{dur}",
         "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(dst)],
        check=True, capture_output=True,
    )


def check() -> str:
    """Teste la clé Groq ; renvoie '' si OK, sinon le problème."""
    try:
        r = httpx.get("https://api.groq.com/openai/v1/models", timeout=15,
                      headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY'].strip()}"})
    except Exception as exc:
        return f"Groq injoignable ({exc.__class__.__name__})"
    if r.status_code == 401:
        return "clé Groq refusée"
    return "" if r.status_code < 400 else f"Groq a répondu {r.status_code}"


def _post(audio: Path, language: str | None) -> dict:
    data = [("model", MODEL), ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "word"), ("timestamp_granularities[]", "segment")]
    if language:
        data.append(("language", language))
    headers = {"Authorization": f"Bearer {os.environ['GROQ_API_KEY'].strip()}"}
    for attempt in range(5):
        with audio.open("rb") as f:
            r = httpx.post(URL, headers=headers, data=data,
                           files={"file": (audio.name, f, "audio/mpeg")}, timeout=300)
        if r.status_code == 429:  # limite de l'offre gratuite : on patiente
            time.sleep(min(float(r.headers.get("retry-after", 20)), 60))
            continue
        if r.status_code == 401:
            raise RuntimeError("clé Groq refusée (vérifie GROQ_API_KEY dans .env)")
        if r.status_code >= 400:
            try:
                detail = r.json().get("error", {}).get("message", "")
            except Exception:
                detail = r.text[:200]
            raise RuntimeError(f"Groq a répondu {r.status_code} : {detail}")
        return r.json()
    raise RuntimeError("limite Groq atteinte, réessaie plus tard")


def transcribe(path: Path, duration: float, progress, language: str | None = None) -> dict:
    segments: list[dict] = []
    lang = language
    n = max(1, int(-(-duration // CHUNK)))
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(n):
            progress(i / n, f"Transcription en ligne… ({i + 1}/{n})")
            offset = i * CHUNK
            part = Path(tmp) / f"part{i}.mp3"
            _encode(path, part, offset, CHUNK)
            res = _post(part, language)
            lang = lang or res.get("language")
            words = [{"start": round(w["start"] + offset, 2), "end": round(w["end"] + offset, 2),
                      "word": w["word"].strip()} for w in res.get("words") or [] if w["word"].strip()]
            for s in res.get("segments") or []:
                start, end = s["start"] + offset, s["end"] + offset
                text = s["text"].strip()
                if not text:
                    continue
                segments.append({
                    "start": round(start, 2), "end": round(end, 2), "text": text,
                    "words": [w for w in words if start - 0.05 <= w["start"] < end],
                })
    progress(1.0, "Transcription terminée")
    return {"language": (lang or "").lower() or None, "segments": segments}
