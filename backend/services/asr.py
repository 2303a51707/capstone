"""
asr.py - multilingual speech recognition.

faster-whisper is preferred (4-5x quicker on CPU, same weights); openai-whisper is the
fallback. Either way the model is multilingual, so the same code path serves every
supported language and new languages need no code change.

The browser's Web Speech API is wired up in the frontend as a zero-install path for a
classroom demo. This module is the server-side path: it is what you use when the
recording must be processed reliably, offline, or on a device whose browser has no
speech support.

Quality gating matters here. Whisper hallucinates fluent text on silence or noise, and
a hallucinated sentence in a police complaint is a serious failure. Segments whose
no-speech probability is high or whose average log-probability is poor are rejected
with an honest error instead of being passed downstream.
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Dict, Optional

from .. import config

log = logging.getLogger("nyayavoice.asr")

_MODEL = None
_BACKEND = None
_LOAD_ERROR = None

# Whisper's known failure mode: it emits these on silence. Never forward them.
_HALLUCINATION_MARKERS = {
    "thank you", "thanks for watching", "thank you for watching", "subtitles by",
    "amara.org", "please subscribe", "bye", "you", "музыка", "ご視聴ありがとうございました",
}

MIN_AVG_LOGPROB = -1.0      # below this the transcript is unreliable
MAX_NO_SPEECH_PROB = 0.65   # above this there probably was no speech at all


def _load():
    global _MODEL, _BACKEND, _LOAD_ERROR
    if _MODEL is not None or _LOAD_ERROR is not None:
        return _MODEL
    try:
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(config.WHISPER_MODEL, device=config.WHISPER_DEVICE,
                              compute_type=config.WHISPER_COMPUTE)
        _BACKEND = "faster-whisper"
        log.info("ASR backend: faster-whisper (%s)", config.WHISPER_MODEL)
        return _MODEL
    except Exception as exc:
        log.warning("faster-whisper unavailable: %s", exc)
    try:
        import whisper
        _MODEL = whisper.load_model(config.WHISPER_MODEL)
        _BACKEND = "openai-whisper"
        log.info("ASR backend: openai-whisper (%s)", config.WHISPER_MODEL)
        return _MODEL
    except Exception as exc:
        _LOAD_ERROR = (
            f"No speech-recognition backend available ({exc}). "
            f"Install one with:  pip install faster-whisper   (recommended)  "
            f"or  pip install openai-whisper. The browser speech path in the UI "
            f"continues to work without this."
        )
        log.error(_LOAD_ERROR)
        return None


def status() -> Dict:
    _load()
    return {
        "available": _MODEL is not None,
        "backend": _BACKEND,
        "model": config.WHISPER_MODEL if _MODEL else None,
        "device": config.WHISPER_DEVICE,
        "error": _LOAD_ERROR,
        "supported_languages": sorted(config.LANGUAGES.keys()),
    }


def _looks_hallucinated(text: str) -> bool:
    stripped = text.strip().lower().strip(".!?, ")
    return stripped in _HALLUCINATION_MARKERS or len(stripped) < 2


def transcribe(audio_bytes: bytes, language: Optional[str] = None,
               filename_hint: str = ".webm") -> Dict:
    """Transcribe audio. language=None asks Whisper to detect the spoken language."""
    model = _load()
    if model is None:
        return {"ok": False, "error_code": "asr_unavailable", "error": _LOAD_ERROR}
    if not audio_bytes or len(audio_bytes) < 1200:
        return {"ok": False, "error_code": "no_audio",
                "error": "The recording is empty or too short. Please tap the microphone "
                         "and speak for a few seconds."}

    suffix = filename_hint if filename_hint.startswith(".") else ".webm"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        whisper_lang = config.LANGUAGES.get(language, {}).get("whisper") if language else None

        if _BACKEND == "faster-whisper":
            segments, info = model.transcribe(
                tmp_path, language=whisper_lang, task="transcribe",
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 600},
                beam_size=5, condition_on_previous_text=False,
            )
            segments = list(segments)
            detected = info.language
            detect_prob = float(info.language_probability or 0)
            duration = float(info.duration or 0)
            kept, logprobs = [], []
            for seg in segments:
                if getattr(seg, "no_speech_prob", 0) > MAX_NO_SPEECH_PROB:
                    continue
                if _looks_hallucinated(seg.text):
                    continue
                kept.append(seg.text.strip())
                logprobs.append(getattr(seg, "avg_logprob", 0.0))
            text = " ".join(kept).strip()
            avg_logprob = sum(logprobs) / len(logprobs) if logprobs else -99
        else:
            result = model.transcribe(tmp_path, language=whisper_lang, task="transcribe",
                                      fp16=False)
            detected = result.get("language", language or "en")
            detect_prob = 0.0
            duration = 0.0
            pieces, logprobs = [], []
            for seg in result.get("segments", []):
                if seg.get("no_speech_prob", 0) > MAX_NO_SPEECH_PROB:
                    continue
                if _looks_hallucinated(seg.get("text", "")):
                    continue
                pieces.append(seg["text"].strip())
                logprobs.append(seg.get("avg_logprob", 0.0))
            text = " ".join(pieces).strip() or result.get("text", "").strip()
            avg_logprob = sum(logprobs) / len(logprobs) if logprobs else -99

        if not text:
            return {"ok": False, "error_code": "no_speech",
                    "error": "We could not clearly understand the recording. Please try again "
                             "in a quieter place, holding the phone closer to your mouth.",
                    "duration": duration}

        if avg_logprob < MIN_AVG_LOGPROB:
            return {"ok": False, "error_code": "low_confidence",
                    "error": "The recording was too unclear to transcribe reliably. Please "
                             "record again in a quieter environment, or type your complaint "
                             "instead.",
                    "partial_text": text, "duration": duration,
                    "quality": round(avg_logprob, 3)}

        language_code = detected if detected in config.LANGUAGES else (language or "en")
        return {
            "ok": True,
            "text": text,
            "language": language_code,
            "language_name": config.lang_name(language_code),
            "language_detected": language is None,
            "detection_confidence": round(detect_prob, 3),
            "duration_seconds": round(duration, 1),
            "quality": {
                "avg_logprob": round(avg_logprob, 3),
                "label": "Good" if avg_logprob > -0.55 else "Fair",
            },
            "backend": _BACKEND,
            "model": config.WHISPER_MODEL,
            "note": "Automatic transcription. Please read it and correct anything that is wrong "
                    "before continuing - the corrected text is what gets analysed.",
        }
    except Exception as exc:
        log.exception("transcription failed")
        return {"ok": False, "error_code": "asr_failed",
                "error": f"Transcription failed ({type(exc).__name__}). If the audio format is "
                         f"unusual, install ffmpeg and try again."}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
