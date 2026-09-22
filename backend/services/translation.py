"""
translation.py - the language bridge.

    citizen's language  ->  English  ->  NLP / legal analysis
                                     ->  police station's regional language

Providers are tried in the order set by config.TRANSLATION_PROVIDERS and the first
one that loads is used for the session. If every provider fails, the text is returned
UNCHANGED with translated=False and a visible error - it is never silently passed off
as a translation, because an officer reading a fabricated translation is worse than an
officer seeing "translation unavailable".
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Dict, List, Optional

from .. import config

log = logging.getLogger("nyayavoice.translation")

_PROVIDER = None
_PROVIDER_NAME = None
_INIT_TRIED = False
_INIT_ERRORS: List[str] = []
_INIT_LOCK = threading.Lock()

# Terms that must survive translation untouched. Section numbers and legal citations
# get mangled by general-purpose MT, so they are masked out and restored afterwards.
_PROTECT_RE = re.compile(
    r"(BNS\s*(?:Section\s*)?\d+[A-Za-z()0-9]*|IPC\s*(?:Section\s*)?\d+[A-Za-z]*|"
    r"Section\s+\d+[A-Za-z()0-9]*|BNSS\s*\d+|₹\s?[\d,]+|Rs\.?\s?[\d,]+|"
    r"\b[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{3,4}\b|\b[6-9]\d{9}\b|NV-\d{4}-\d+)"
)


# ------------------------------------------------------------------ providers
class GoogleProvider:
    """deep-translator's Google backend. No API key, needs internet, good Indic quality."""
    name = "google"

    # Google allows roughly 5 requests/second. build_regional() translates every
    # field and every label separately, so one FIR is 40+ calls - without pacing
    # they arrive as a burst and the endpoint starts returning TooManyRequests.
    _MIN_INTERVAL = 0.25
    _RETRIES = 3

    def __init__(self):
        from deep_translator import GoogleTranslator
        from deep_translator.exceptions import TooManyRequests
        self._cls = GoogleTranslator
        self._TooManyRequests = TooManyRequests
        self._lock = threading.Lock()
        self._last_call = 0.0
        # Do not make a startup translation request. The public endpoint may rate-limit
        # even a harmless probe, and the real request below already handles retries.

    def _call(self, fn, *args):
        for attempt in range(self._RETRIES):
            with self._lock:
                wait = self._MIN_INTERVAL - (time.monotonic() - self._last_call)
                if wait > 0:
                    time.sleep(wait)
                self._last_call = time.monotonic()
            try:
                return fn(*args)
            except self._TooManyRequests:
                if attempt == self._RETRIES - 1:
                    raise
                backoff = 2 ** attempt
                log.warning("google rate-limited, retrying in %ss", backoff)
                time.sleep(backoff)

    def translate(self, text: str, src: str, tgt: str) -> str:
        src_code = config.LANGUAGES.get(src, {}).get("google", src)
        tgt_code = config.LANGUAGES.get(tgt, {}).get("google", tgt)
        chunks, out = _chunk(text, 4500), []
        for chunk in chunks:
            translator = self._cls(source=src_code or "auto", target=tgt_code)
            out.append(self._call(translator.translate, chunk))
        return " ".join(p for p in out if p)

    def translate_many(self, texts: List[str], src: str, tgt: str) -> List[str]:
        """One request for the whole FIR instead of 44, which is what tripped the
        5-requests-per-second limit in the first place."""
        if not texts:
            return []
        src_code = config.LANGUAGES.get(src, {}).get("google", src)
        tgt_code = config.LANGUAGES.get(tgt, {}).get("google", tgt)
        translator = self._cls(source=src_code or "auto", target=tgt_code)
        # translate_batch rejects empty strings, so hold their positions out.
        indexed = [(i, t) for i, t in enumerate(texts) if t.strip()]
        if not indexed:
            return list(texts)
        results = self._call(translator.translate_batch, [t for _, t in indexed])
        out = list(texts)
        for (i, original), translated in zip(indexed, results):
            out[i] = translated or original
        return out


class MyMemoryProvider:
    """Direct MyMemory REST API fallback.

    We intentionally call the official MyMemory endpoint directly instead of
    deep-translator's MyMemory wrapper. The wrapper validates against its own
    language table, which can reject valid RFC3066/ISO language pairs such as
    Telugu (te) even though the MyMemory API accepts them. The API also limits
    each query to 500 bytes, so requests are chunked accordingly.
    """
    name = "mymemory"
    _MIN_INTERVAL = 0.75
    _TIMEOUT = 20
    _MAX_BYTES = 500

    def __init__(self):
        import requests
        self._requests = requests
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._url = "https://api.mymemory.translated.net/get"
        # Optional: setting MYMEMORY_EMAIL can increase the daily anonymous
        # allowance according to MyMemory's API documentation.
        self._email = os.environ.get("MYMEMORY_EMAIL", "").strip()

    @staticmethod
    def _api_code(code: str) -> str:
        # MyMemory accepts ISO language codes and RFC3066 tags.
        aliases = {
            "en": "en", "te": "te", "hi": "hi", "ta": "ta", "kn": "kn",
            "ml": "ml", "mr": "mr", "bn": "bn", "gu": "gu", "pa": "pa",
            "or": "or", "ur": "ur", "as": "as",
        }
        return aliases.get(code, code)

    @classmethod
    def _byte_chunks(cls, text: str):
        """Yield UTF-8 chunks no larger than MyMemory's 500-byte query limit."""
        text = text.strip()
        if not text:
            return []

        chunks, buf = [], ""
        for sentence in _split_sentences(text):
            candidate = f"{buf} {sentence}".strip() if buf else sentence
            if len(candidate.encode("utf-8")) <= cls._MAX_BYTES:
                buf = candidate
                continue

            if buf:
                chunks.append(buf)
                buf = ""

            # A single sentence can itself exceed 500 bytes.
            current = ""
            for word in sentence.split():
                candidate = f"{current} {word}".strip() if current else word
                if len(candidate.encode("utf-8")) <= cls._MAX_BYTES:
                    current = candidate
                else:
                    if current:
                        chunks.append(current)
                    current = word
            if current:
                buf = current

        if buf:
            chunks.append(buf)
        return chunks or [text]

    def _request(self, text: str, src: str, tgt: str) -> str:
        with self._lock:
            wait = self._MIN_INTERVAL - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

        params = {
            "q": text,
            "langpair": f"{self._api_code(src)}|{self._api_code(tgt)}",
            "mt": "1",
        }
        if self._email:
            params["de"] = self._email

        response = self._requests.get(self._url, params=params, timeout=self._TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if data.get("quotaFinished"):
            raise RuntimeError("MyMemory quota is exhausted.")

        status = data.get("responseStatus")
        if status not in (None, 200, "200"):
            detail = data.get("responseDetails") or f"responseStatus={status}"
            raise RuntimeError(f"MyMemory translation failed: {detail}")

        translated = (data.get("responseData") or {}).get("translatedText")
        if not translated:
            raise RuntimeError("MyMemory returned an empty translation.")
        return translated

    def translate(self, text: str, src: str, tgt: str) -> str:
        return " ".join(
            self._request(chunk, src, tgt)
            for chunk in self._byte_chunks(text)
        )

    def translate_many(self, texts: List[str], src: str, tgt: str) -> List[str]:
        return [
            self.translate(t, src, tgt) if t.strip() else t
            for t in texts
        ]


class IndicTrans2Provider:
    """AI4Bharat IndicTrans2 - built for Indian languages, runs offline after download."""
    name = "indictrans2"

    def __init__(self):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        from IndicTransToolkit.processor import IndicProcessor
        self._torch = torch
        self._ip = IndicProcessor(inference=True)
        self._models = {}
        self._AutoModel = AutoModelForSeq2SeqLM
        self._AutoTok = AutoTokenizer
        self._repos = {
            "indic-en": "ai4bharat/indictrans2-indic-en-dist-200M",
            "en-indic": "ai4bharat/indictrans2-en-indic-dist-200M",
        }
        self._get("indic-en")

    def _get(self, key):
        if key not in self._models:
            repo = self._repos[key]
            tok = self._AutoTok.from_pretrained(repo, trust_remote_code=True)
            model = self._AutoModel.from_pretrained(repo, trust_remote_code=True)
            model.eval()
            self._models[key] = (tok, model)
        return self._models[key]

    def translate(self, text: str, src: str, tgt: str) -> str:
        # Only two checkpoints are loaded, so an Indic->Indic pair has to pivot
        # through English. Without this, te->ta would be handed to the en-indic
        # model with Telugu input: it returns fluent, wrong Tamil of roughly the
        # right length, which no downstream check would catch.
        if src != "en" and tgt != "en":
            return self._direct(self._direct(text, src, "en"), "en", tgt)
        return self._direct(text, src, tgt)

    def _direct(self, text: str, src: str, tgt: str) -> str:
        direction = "indic-en" if tgt == "en" else "en-indic"
        tok, model = self._get(direction)
        src_tag = config.LANGUAGES[src]["flores"]
        tgt_tag = config.LANGUAGES[tgt]["flores"]
        sentences = _split_sentences(text)
        batch = self._ip.preprocess_batch(sentences, src_lang=src_tag, tgt_lang=tgt_tag)
        enc = tok(batch, truncation=True, padding="longest", return_tensors="pt")
        with self._torch.inference_mode():
            generated = model.generate(**enc, num_beams=5, max_length=256)
        decoded = tok.batch_decode(generated, skip_special_tokens=True)
        return " ".join(self._ip.postprocess_batch(decoded, lang=tgt_tag))


class NLLBProvider:
    """Meta NLLB-200 distilled. Wide coverage, offline after the first download.

    Driven through tokenize/generate/decode rather than pipeline("translation"):
    the translation, summarization and text2text-generation pipeline tasks were
    removed in transformers v5, and the manual path works on v4 and v5 alike.
    """
    name = "nllb"

    # One FIR is ~44 short strings. Sent one at a time with beam search this is
    # minutes of CPU; batched and greedy it is seconds. Raise _BEAMS to 4 if you
    # have a GPU and want the extra quality.
    _BEAMS = 1
    _BATCH = 16

    def __init__(self):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        self._torch = torch
        self._repo = "facebook/nllb-200-distilled-600M"
        self._tok = AutoTokenizer.from_pretrained(self._repo)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(self._repo)
        self._model.eval()

    def _lang_token(self, tag: str) -> int:
        """FLORES tag -> token id. lang_code_to_id was dropped from the tokenizer."""
        token_id = self._tok.convert_tokens_to_ids(tag)
        if token_id is None or token_id == self._tok.unk_token_id:
            raise ValueError(f"NLLB does not recognise the language tag {tag!r}")
        return token_id

    def translate(self, text: str, src: str, tgt: str) -> str:
        return self.translate_many([text], src, tgt)[0]

    def translate_many(self, texts: List[str], src: str, tgt: str) -> List[str]:
        if not texts:
            return []
        self._tok.src_lang = config.LANGUAGES[src]["flores"]
        bos = self._lang_token(config.LANGUAGES[tgt]["flores"])

        # Flatten every sentence of every field into one padded batch, keeping a
        # span per input so the results can be reassembled field by field.
        flat, spans = [], []
        for text in texts:
            sentences = _split_sentences(text)
            spans.append((len(flat), len(flat) + len(sentences)))
            flat.extend(sentences)

        decoded = []
        for i in range(0, len(flat), self._BATCH):
            enc = self._tok(flat[i:i + self._BATCH], return_tensors="pt",
                            padding=True, truncation=True, max_length=400)
            with self._torch.inference_mode():
                generated = self._model.generate(
                    **enc, forced_bos_token_id=bos,
                    max_length=400, num_beams=self._BEAMS,
                )
            decoded.extend(self._tok.batch_decode(generated, skip_special_tokens=True))
        return [" ".join(decoded[a:b]) for a, b in spans]


_REGISTRY = {"google": GoogleProvider, "mymemory": MyMemoryProvider, "indictrans2": IndicTrans2Provider, "nllb": NLLBProvider}


def _init_provider():
    """Resolve the provider once. Retrying on every call would re-import torch and
    re-log the same failure for each field of an FIR."""
    global _PROVIDER, _PROVIDER_NAME, _INIT_TRIED
    if _PROVIDER is not None or _INIT_TRIED:
        return _PROVIDER
    with _INIT_LOCK:
        # Re-check: a thread may have finished initialising while this one waited.
        if _PROVIDER is not None or _INIT_TRIED:
            return _PROVIDER
        return _init_provider_locked()


def _init_provider_locked():
    global _PROVIDER, _PROVIDER_NAME, _INIT_TRIED
    _INIT_TRIED = True
    for name in config.TRANSLATION_PROVIDERS:
        name = name.strip()
        cls = _REGISTRY.get(name)
        if not cls:
            continue
        try:
            _PROVIDER = cls()
            _PROVIDER_NAME = name
            log.info("translation provider: %s", name)
            return _PROVIDER
        except Exception as exc:
            _INIT_ERRORS.append(f"{name}: {type(exc).__name__}: {exc}")
            log.warning("translation provider %s unavailable: %s", name, exc)
    return None


# ------------------------------------------------------------------- helpers
def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?।])\s+", text.strip())
    return [p for p in parts if p.strip()] or [text]


def _chunk(text: str, size: int) -> List[str]:
    if len(text) <= size:
        return [text]
    out, buf = [], ""
    for sentence in _split_sentences(text):
        if len(buf) + len(sentence) + 1 > size:
            out.append(buf)
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
    if buf:
        out.append(buf)
    return out


_SENTINEL_RE = re.compile(r"NVX\s*(\d+)\s*XVN", re.IGNORECASE)


def _protect(text: str):
    """Mask spans that must survive translation byte-for-byte.

    The sentinel is alphanumeric rather than punctuation: MT engines respace,
    strip or reorder runs like '§§0§§', but leave an unknown alphanumeric token
    alone because it looks like a proper noun.
    """
    tokens = {}

    def sub(match):
        key = f"NVX{len(tokens)}XVN"
        tokens[key] = match.group(0)
        return key
    return _PROTECT_RE.sub(sub, text), tokens


def _restore(text: str, tokens: Dict[str, str]):
    """Restore protected spans. Returns (text, lost_values).

    There is deliberately no fallback to replacing the bare index. Substituting
    every '0' in the output would rewrite unrelated digits - including digits
    inside values restored by an earlier iteration - and emit a fabricated
    section number that reads as legitimate. Anything that cannot be restored
    exactly is reported to the caller instead of guessed at.
    """
    for key, value in tokens.items():
        text = text.replace(key, value)

    # Tolerate an engine that respaced or recased the sentinel, but only where
    # the index is still readable and therefore unambiguous.
    def _by_index(match):
        return tokens.get(f"NVX{match.group(1)}XVN", match.group(0))
    text = _SENTINEL_RE.sub(_by_index, text)

    # A sentinel the engine dropped altogether leaves no trace, so verify by
    # value: a missing section number or amount is silent data loss otherwise.
    lost = [value for value in tokens.values() if value not in text]
    return text, lost


# ---------------------------------------------------------------------- public
def reset_provider():
    """Force re-detection, e.g. after installing a provider without restarting."""
    global _PROVIDER, _PROVIDER_NAME, _INIT_TRIED
    _PROVIDER, _PROVIDER_NAME, _INIT_TRIED = None, None, False
    _INIT_ERRORS.clear()
    _MEMO.clear()


def provider_status() -> Dict:
    _init_provider()
    return {
        "active_provider": _PROVIDER_NAME,
        "available": _PROVIDER is not None,
        "configured_order": config.TRANSLATION_PROVIDERS,
        "errors": _INIT_ERRORS,
    }


def detect_language(text: str) -> Dict:
    """Script-based detection first (unambiguous for Indic scripts), then langdetect."""
    ranges = {
        "te": (0x0C00, 0x0C7F), "kn": (0x0C80, 0x0CFF), "ml": (0x0D00, 0x0D7F),
        "ta": (0x0B80, 0x0BFF), "bn": (0x0980, 0x09FF), "gu": (0x0A80, 0x0AFF),
        "pa": (0x0A00, 0x0A7F), "or": (0x0B00, 0x0B7F), "hi": (0x0900, 0x097F),
        "ur": (0x0600, 0x06FF),
    }
    counts = {code: 0 for code in ranges}
    latin = 0
    for ch in text:
        point = ord(ch)
        if "a" <= ch.lower() <= "z":
            latin += 1
            continue
        for code, (low, high) in ranges.items():
            if low <= point <= high:
                counts[code] += 1
                break

    best = max(counts, key=counts.get)
    total = sum(counts.values())
    # `total >= latin` matters: without it a romanised complaint containing one
    # Devanagari word scores 4/4 on the Indic ratio and is returned as Hindi at
    # 0.08 confidence, instead of falling through to langdetect.
    if total >= 3 and total >= latin and counts[best] / max(total, 1) > 0.5:
        # Held before disambiguation: the codes below ('mr', 'as') are language
        # names, not script names, so they have no entry in `counts`.
        script_count = counts[best]
        # Hindi and Marathi share Devanagari - disambiguate with marker words
        if best == "hi":
            marathi = ("आहे", "माझ्या", "मला", "झाले", "त्याने", "नाही", "केले")
            if any(w in text for w in marathi):
                best = "mr"
        elif best == "bn":
            # Assamese shares the Bengali block but has two letters of its own:
            # ৰ (U+09F0) and ৱ (U+09F1), where Bengali writes র and ব.
            if "\u09f0" in text or "\u09f1" in text:
                best = "as"
        return {"language": best, "language_name": config.lang_name(best),
                "confidence": round(script_count / max(total + latin, 1), 3), "method": "script"}

    # Latin wins on a clear majority, not only when the Indic count is exactly
    # zero - a stray Devanagari character in an otherwise romanised complaint
    # used to fall through to the 0.3-confidence default.
    if latin > 0 and latin > total * 2:
        try:
            from langdetect import detect_langs
            guesses = detect_langs(text)
            top = guesses[0]
            code = top.lang if top.lang in config.LANGUAGES else "en"
            return {"language": code, "language_name": config.lang_name(code),
                    "confidence": round(top.prob, 3), "method": "langdetect"}
        except Exception:
            pass
        return {"language": "en", "language_name": "English", "confidence": 0.6,
                "method": "latin-script fallback"}

    return {"language": "en", "language_name": "English", "confidence": 0.3,
            "method": "default", "warning": "Language could not be determined confidently."}


_MEMO: Dict[tuple, str] = {}
_MEMO_MAX = 2048


def _memo_put(key: tuple, value: str):
    if len(_MEMO) >= _MEMO_MAX:
        _MEMO.clear()
    _MEMO[key] = value


def _failover(failed_name: Optional[str], exc: Exception):
    """Swap in the next configured provider after a *runtime* failure.

    _init_provider only handles providers that fail to load. A provider can load
    cleanly and then start refusing calls - Google rate-limiting an IP is the
    common case - and without this the session stays pinned to it forever.
    """
    global _PROVIDER, _PROVIDER_NAME
    with _INIT_LOCK:
        if _PROVIDER_NAME != failed_name:
            return _PROVIDER                  # another thread already moved on
        order = [n.strip() for n in config.TRANSLATION_PROVIDERS]
        remaining = order[order.index(failed_name) + 1:] if failed_name in order else []
        _INIT_ERRORS.append(f"{failed_name}: runtime: {type(exc).__name__}: {exc}")
        for name in remaining:
            cls = _REGISTRY.get(name)
            if not cls:
                continue
            try:
                _PROVIDER, _PROVIDER_NAME = cls(), name
                log.warning("provider %s failed at runtime (%s); switched to %s",
                            failed_name, type(exc).__name__, name)
                return _PROVIDER
            except Exception as load_exc:
                _INIT_ERRORS.append(f"{name}: {type(load_exc).__name__}: {load_exc}")
        log.error("provider %s failed and no fallback loaded", failed_name)
        _PROVIDER, _PROVIDER_NAME = None, None
        return None


def _with_failover(call):
    """Run a provider call, retrying once on the next provider if it raises."""
    provider = _init_provider()
    if provider is None:
        raise RuntimeError("No translation provider is available.")
    active = _PROVIDER_NAME
    try:
        return call(provider)
    except Exception as exc:
        fallback = _failover(active, exc)
        if fallback is None:
            raise
        return call(fallback)


def _cached(text: str, src: str, tgt: str) -> str:
    key = (text, src, tgt)
    if key in _MEMO:
        return _MEMO[key]
    out = _with_failover(lambda p: p.translate(text, src, tgt))
    _memo_put(key, out)
    return out


def _cached_many(texts: List[str], src: str, tgt: str) -> List[str]:
    """Translate a list, sending only cache misses to the provider.

    The ~20 FIR field labels are identical for every complaint, so after the
    first draft they cost nothing.
    """
    pending = [t for t in dict.fromkeys(texts) if (t, src, tgt) not in _MEMO]
    if pending:
        def run(provider):
            if hasattr(provider, "translate_many"):
                return provider.translate_many(pending, src, tgt)
            return [provider.translate(t, src, tgt) for t in pending]
        fresh = _with_failover(run)
        for original, translated in zip(pending, fresh):
            _memo_put((original, src, tgt), translated)
    return [_MEMO[(t, src, tgt)] for t in texts]


def translate(text: str, source: str, target: str) -> Dict:
    """Translate, preserving section numbers, amounts and identifiers verbatim."""
    text = (text or "").strip()
    if not text:
        return {"text": "", "translated": False, "provider": None,
                "error": "Nothing to translate."}
    if source == target:
        return {"text": text, "translated": False, "provider": None,
                "source": source, "target": target, "note": "Source and target are the same."}

    provider = _init_provider()
    if provider is None:
        return {
            "text": text, "translated": False, "provider": None,
            "source": source, "target": target,
            "error": "No translation provider is available. The text below is the ORIGINAL, "
                     "untranslated. Install deep-translator (pip install deep-translator) or "
                     "configure IndicTrans2 / NLLB, then retry.",
            "provider_errors": _INIT_ERRORS,
        }

    masked, tokens = _protect(text)
    try:
        out = _cached(masked, source, target)
        out, lost = _restore(out, tokens)
        result = {
            "text": out, "translated": True, "provider": _PROVIDER_NAME,
            "source": source, "target": target,
            "source_name": config.lang_name(source), "target_name": config.lang_name(target),
            "confidence": _quality(text, out, lost),
        }
        if lost:
            result["lost_terms"] = lost
            result["warning"] = (
                "The translation engine dropped " + str(len(lost)) + " protected term(s) "
                "(" + ", ".join(lost) + "). They are missing from the translated text - "
                "read them from the original."
            )
        return result
    except Exception as exc:
        log.exception("translation failed")
        return {
            "text": text, "translated": False, "provider": _PROVIDER_NAME,
            "source": source, "target": target,
            "error": f"Translation failed ({type(exc).__name__}). The ORIGINAL text is shown "
                     f"unchanged - it has not been translated.",
        }


def _quality(source_text: str, translated_text: str, lost: Optional[List[str]] = None) -> Dict:
    """A transparent heuristic, deliberately not presented as a model score."""
    if not translated_text.strip():
        return {"score": 0, "label": "Failed", "basis": "empty output"}
    ratio = len(translated_text) / max(len(source_text), 1)
    score = 92
    notes = []
    if lost:
        # Pushes the score under the 60 threshold app.py warns on, on its own.
        score -= 40
        notes.append(f"{len(lost)} protected term(s) missing from the output")
    if ratio < 0.35 or ratio > 3.0:
        score -= 25
        notes.append("output length differs sharply from the input")
    if translated_text.strip() == source_text.strip():
        score -= 45
        notes.append("output is identical to the input")
    if len(source_text.split()) < 5:
        score -= 10
        notes.append("very short input")
    score = max(10, min(98, score))
    return {
        "score": score,
        "label": "High" if score >= 80 else "Moderate" if score >= 55 else "Low",
        "basis": "; ".join(notes) or "length and content consistency checks passed",
        "caveat": "A heuristic indicator of output plausibility, not a measure of legal accuracy. "
                  "The original transcript is always retained for comparison.",
    }


def translate_many(texts: List[str], source: str, target: str) -> List[Dict]:
    """Batch form of translate(). Same per-item result dicts, one provider round trip."""
    results: List[Optional[Dict]] = [None] * len(texts)
    todo = []
    for i, raw in enumerate(texts):
        text = (raw or "").strip()
        if not text:
            results[i] = {"text": "", "translated": False, "provider": None,
                          "error": "Nothing to translate."}
        elif source == target:
            results[i] = {"text": text, "translated": False, "provider": None,
                          "source": source, "target": target,
                          "note": "Source and target are the same."}
        else:
            todo.append((i, text))

    if not todo:
        return [r for r in results if r is not None]

    provider = _init_provider()
    if provider is None:
        for i, text in todo:
            results[i] = translate(text, source, target)   # returns the unavailable error
        return [r for r in results if r is not None]

    masked_list, token_list = [], []
    for _, text in todo:
        masked, tokens = _protect(text)
        masked_list.append(masked)
        token_list.append(tokens)

    try:
        outputs = _cached_many(masked_list, source, target)
    except Exception as exc:
        log.exception("batch translation failed")
        for i, text in todo:
            results[i] = {
                "text": text, "translated": False, "provider": _PROVIDER_NAME,
                "source": source, "target": target,
                "error": f"Translation failed ({type(exc).__name__}). The ORIGINAL text is "
                         f"shown unchanged - it has not been translated.",
            }
        return [r for r in results if r is not None]

    for (i, text), out, tokens in zip(todo, outputs, token_list):
        out, lost = _restore(out, tokens)
        entry = {
            "text": out, "translated": True, "provider": _PROVIDER_NAME,
            "source": source, "target": target,
            "source_name": config.lang_name(source), "target_name": config.lang_name(target),
            "confidence": _quality(text, out, lost),
        }
        if lost:
            entry["lost_terms"] = lost
            entry["warning"] = (
                "The translation engine dropped " + str(len(lost)) + " protected term(s) "
                "(" + ", ".join(lost) + "). They are missing from the translated text - "
                "read them from the original."
            )
        results[i] = entry
    return [r for r in results if r is not None]


def translate_fir(fir: Dict, source: str, target: str) -> Dict:
    """Translate the value side of an FIR dict, leaving structure and keys intact."""
    if source == target:
        return {"fir": fir, "translated": False, "provider": None}
    provider_ok = _init_provider() is not None

    # Collect every string first so the whole FIR is one provider round trip
    # rather than one per field.
    slots, texts = [], []
    for key, value in fir.items():
        if isinstance(value, str) and value.strip():
            slots.append((key, None))
            texts.append(value)
        elif isinstance(value, list):
            for pos, item in enumerate(value):
                if isinstance(item, str) and item.strip():
                    slots.append((key, pos))
                    texts.append(item)

    results = translate_many(texts, source, target) if texts else []
    failures = sum(0 if r.get("translated") else 1 for r in results)

    out = {}
    for key, value in fir.items():
        out[key] = list(value) if isinstance(value, list) else value
    for (key, pos), result in zip(slots, results):
        if pos is None:
            out[key] = result["text"]
        else:
            out[key][pos] = result["text"]

    return {
        "fir": out,
        "translated": provider_ok and failures == 0,
        "provider": _PROVIDER_NAME,
        "partial_failures": failures,
        "target_language": target,
        "target_language_name": config.lang_name(target),
    }
