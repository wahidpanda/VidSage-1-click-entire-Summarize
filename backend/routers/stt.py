"""Speech-to-text with Whisper — runs locally, free, understands 90+ languages
(including Bangla), so voice questions work in any language.

Uses faster-whisper (CPU-friendly). The model is lazy-loaded on first use.
If faster-whisper isn't installed, the endpoint reports it clearly and the
frontend falls back to the browser's built-in speech recognition.
"""
import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from backend.config import WHISPER_MODEL
from backend.security import get_current_user
from backend.models import User

router = APIRouter(prefix="/api/stt", tags=["voice"])

_model = None
_lock = asyncio.Lock()


def _load_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def _transcribe(path: str) -> dict:
    model = _load_model()
    segments, info = model.transcribe(path, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "language": info.language}


@router.post("")
async def transcribe(audio: UploadFile = File(...),
                     user: User = Depends(get_current_user)):
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Whisper isn't installed on the server. Run: pip install faster-whisper",
        )

    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    data = await audio.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio clip is too large (max 25 MB).")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        tmp_path = f.name

    try:
        async with _lock:  # whisper isn't thread-safe; serialize requests
            result = await asyncio.to_thread(_transcribe, tmp_path)
        if not result["text"]:
            raise HTTPException(status_code=422, detail="No speech was detected in the clip.")
        return result
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Couldn't transcribe that clip. Try again.")
    finally:
        Path(tmp_path).unlink(missing_ok=True)
