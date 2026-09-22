"""
app.py - NyayaVoice REST API and static host for the frontend.

Run:  uvicorn backend.app:app --reload --port 8000    (from the project root)
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, database
from .services import asr, fir_builder, legal_engine, nlp_engine, pdf_export, translation

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nyayavoice")

app = FastAPI(
    title="NyayaVoice API",
    version="1.0.0",
    description="Multilingual voice-based FIR writer and legal-provision finder. "
                "Every response is an AI-assisted draft requiring officer verification.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # tighten for a real deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PDF_DIR = os.path.join(tempfile.gettempdir(), "nyayavoice_pdfs")
os.makedirs(PDF_DIR, exist_ok=True)


@app.on_event("startup")
def startup():
    database.init()
    legal_engine.load()
    log.info("legal engine: %s", legal_engine.status())


# ------------------------------------------------------------------- schemas
class TextIn(BaseModel):
    text: str = Field(..., description="Complaint text")


class TranslateIn(BaseModel):
    text: str
    source: str = "auto"
    target: str = "en"


class AnalyzeIn(BaseModel):
    text: str = Field(..., description="Complaint text in the complainant's language or English")
    language: Optional[str] = Field(None, description="Source language; None triggers detection")
    police_region: str = "Telangana"
    police_station: Optional[str] = None
    report_date: Optional[str] = None


class SectionsIn(BaseModel):
    text: str = Field(..., description="Complaint text IN ENGLISH")
    incident_date: Optional[str] = None
    max_results: Optional[int] = None


class GenerateFIRIn(BaseModel):
    original_transcript: str
    english_translation: Optional[str] = None
    original_language: str = "en"
    police_region: str = "Telangana"
    police_station: Optional[str] = None
    entities: Optional[Dict[str, Any]] = None
    provisions: Optional[List[Dict[str, Any]]] = None
    classification: Optional[Dict[str, Any]] = None
    reference_number: Optional[str] = None
    include_regional: bool = True


class PDFIn(BaseModel):
    fir_bundle: Dict[str, Any]
    regional_copy: Optional[Dict[str, Any]] = None
    copies: str = "both"
    include_transcript: bool = True


class ComplaintIn(BaseModel):
    original_language: str = "en"
    police_region: str = "Telangana"
    police_station: Optional[str] = None
    regional_language: Optional[str] = None
    original_transcript: str
    english_translation: str
    crime_type: Optional[str] = None
    crime_confidence: Optional[int] = None
    input_mode: str = "voice"
    status: str = "draft"
    incident_date_iso: Optional[str] = None
    summary: Optional[str] = None
    entities: Optional[Dict[str, Any]] = None
    provisions: Optional[List[Dict[str, Any]]] = None
    english_fir: Optional[Dict[str, Any]] = None
    regional_fir: Optional[Dict[str, Any]] = None
    field_labels: Optional[Dict[str, Any]] = None
    regional_labels: Optional[Dict[str, Any]] = None
    analysis: Optional[Dict[str, Any]] = None
    reference_number: Optional[str] = None


class UpdateComplaintIn(BaseModel):
    crime_type: Optional[str] = None
    status: Optional[str] = None
    police_station: Optional[str] = None
    police_region: Optional[str] = None
    english_translation: Optional[str] = None
    summary: Optional[str] = None
    incident_date_iso: Optional[str] = None
    entities: Optional[Dict[str, Any]] = None
    english_fir: Optional[Dict[str, Any]] = None
    regional_fir: Optional[Dict[str, Any]] = None
    regional_language: Optional[str] = None


# ------------------------------------------------------------------ meta
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "time": datetime.now().isoformat(timespec="seconds"),
        "speech_recognition": asr.status(),
        "translation": translation.provider_status(),
        "legal_engine": legal_engine.status(),
        "pdf": pdf_export.status(),
        "database": config.DB_PATH,
    }


@app.get("/api/config")
def get_config():
    return {
        "languages": [
            {"code": code, "name": meta["name"], "native": meta["native"],
             "script": meta["script"], "speech": meta["speech"]}
            for code, meta in config.LANGUAGES.items()
        ],
        "regions": [
            {"name": name, "language": meta["lang"],
             "language_name": config.lang_name(meta["lang"]), "capital": meta["capital"]}
            for name, meta in sorted(config.REGIONS.items())
        ],
        "disclaimer": config.DISCLAIMER,
        "bns_cutover": config.BNS_CUTOVER,
    }


# ------------------------------------------------------------------ speech
@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...), language: Optional[str] = Form(None)):
    """Speech to text. Omit 'language' to let the model detect the spoken language."""
    payload = await audio.read()
    suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
    lang = None if (language in (None, "", "auto")) else language
    result = asr.transcribe(payload, language=lang, filename_hint=suffix)
    if not result.get("ok"):
        return JSONResponse(status_code=422, content=result)
    return result


@app.post("/api/detect-language")
def detect_language(body: TextIn):
    if not body.text.strip():
        raise HTTPException(400, "text is required")
    return translation.detect_language(body.text)


@app.post("/api/translate")
def do_translate(body: TranslateIn):
    source = body.source
    detected = None
    if source in ("auto", "", None):
        detected = translation.detect_language(body.text)
        source = detected["language"]
    result = translation.translate(body.text, source, body.target)
    if detected:
        result["detected_source"] = detected
    return result


# ------------------------------------------------------------------ analysis
@app.post("/api/find-sections")
def find_sections(body: SectionsIn):
    """Identify potentially relevant provisions from ENGLISH complaint text."""
    if not body.text.strip():
        raise HTTPException(400, "text is required")
    return legal_engine.find_sections(body.text, body.incident_date, body.max_results)


@app.get("/api/provisions/{code:path}")
def get_provision(code: str):
    """Full detail for one provision, e.g. /api/provisions/IPC:379 or /api/provisions/X:BNS304"""
    entry = legal_engine.get_provision(code)
    if not entry:
        raise HTTPException(404, f"No provision with code {code}")
    return entry


@app.post("/api/analyze")
def analyze(body: AnalyzeIn):
    """
    The full understanding pipeline in one call:
      detect language -> translate to English -> extract entities ->
      classify the incident -> find potentially relevant provisions.
    """
    text = body.text.strip()
    if len(text) < 3:
        raise HTTPException(400, "text is too short to analyse")

    detection = translation.detect_language(text)
    source = body.language or detection["language"]

    if source == "en":
        english = text
        translation_result = {"text": text, "translated": False, "provider": None,
                              "note": "The complaint was already in English."}
    else:
        translation_result = translation.translate(text, source, "en")
        english = translation_result["text"]

    report_date = date.today()
    if body.report_date:
        try:
            report_date = datetime.fromisoformat(body.report_date).date()
        except ValueError:
            pass

    extraction = nlp_engine.extract(english, report_date=report_date)
    legal = legal_engine.find_sections(english, extraction.get("resolved_iso_date"))
    classification = legal.get("classification")
    summary = nlp_engine.summarise(english, extraction["entities"],
                                   (classification or {}).get("label"))

    regional_language = config.region_language(body.police_region)

    return {
        "original_transcript": text,
        "original_language": source,
        "original_language_name": config.lang_name(source),
        "language_detection": detection,
        "english_translation": english,
        "translation": translation_result,
        "police_region": body.police_region,
        "police_station": body.police_station,
        "regional_language": regional_language,
        "regional_language_name": config.lang_name(regional_language),
        "entities": extraction["entities"],
        "extraction_meta": {
            "n_extracted": extraction["n_extracted"],
            "missing_fields": extraction["missing_fields"],
            "follow_up_questions": extraction["follow_up_questions"],
            "date_derivation": extraction["date_derivation"],
            "extractor": extraction["extractor"],
        },
        "incident_date_iso": extraction["resolved_iso_date"],
        "classification": classification,
        "alternative_classifications": legal.get("alternative_classifications", []),
        "provisions": legal["provisions"],
        "advisories": legal.get("advisories", []),
        "law_regime": legal.get("law_regime"),
        "signals_used": legal.get("signals_used", []),
        "summary": summary,
        "disclaimer": config.DISCLAIMER,
        "warnings": _warnings(translation_result, extraction, legal),
    }


def _warnings(translation_result, extraction, legal) -> List[Dict[str, str]]:
    out = []
    if translation_result.get("error"):
        out.append({"level": "error", "message": translation_result["error"]})
    elif translation_result.get("translated") and \
            translation_result.get("confidence", {}).get("score", 100) < 60:
        out.append({"level": "warning",
                    "message": "Translation quality looks low. Please compare it with the "
                               "original transcript before relying on it."})
    if extraction["n_extracted"] < 3:
        out.append({"level": "warning",
                    "message": "Very few details could be extracted. The officer should ask the "
                               "follow-up questions listed before the draft is used."})
    if not legal["provisions"]:
        out.append({"level": "warning",
                    "message": "No legal provision reached the confidence threshold. The "
                               "complaint is recorded in full for the duty officer to assess."})
    return out


# ------------------------------------------------------------------ FIR
@app.post("/api/generate-fir")
def generate_fir(body: GenerateFIRIn):
    """Build the English FIR draft and the police station's regional-language copy."""
    english = body.english_translation
    if not english:
        if body.original_language == "en":
            english = body.original_transcript
        else:
            result = translation.translate(body.original_transcript, body.original_language, "en")
            english = result["text"]

    entities = body.entities
    if entities is None:
        entities = nlp_engine.extract(english)["entities"]

    provisions = body.provisions
    classification = body.classification
    law_regime = None
    if provisions is None:
        legal = legal_engine.find_sections(english)
        provisions = legal["provisions"]
        classification = classification or legal["classification"]
        law_regime = legal["law_regime"]

    summary = nlp_engine.summarise(english, entities, (classification or {}).get("label"))

    bundle = fir_builder.build(
        transcript_original=body.original_transcript,
        transcript_english=english,
        entities=entities,
        provisions=provisions,
        classification=classification,
        original_language=body.original_language,
        police_region=body.police_region,
        police_station=body.police_station,
        reference=body.reference_number or database.next_reference(),
        law_regime=law_regime,
        summary=summary,
    )

    regional = fir_builder.build_regional(bundle) if body.include_regional else None

    return {
        "english": bundle,
        "regional": regional,
        "provisions": provisions,
        "classification": classification,
        "disclaimer": config.DISCLAIMER,
    }


@app.post("/api/generate-pdf")
def generate_pdf(body: PDFIn):
    """Render the FIR to PDF. Returns a download URL."""
    bundle = body.fir_bundle
    if "fir" not in bundle:
        raise HTTPException(400, "fir_bundle must contain a 'fir' object")
    reference = bundle["fir"].get("reference_number", "NV-draft")
    filename = f"{reference}-{datetime.now().strftime('%H%M%S')}.pdf"
    out_path = os.path.join(PDF_DIR, filename)

    result = pdf_export.generate(bundle, body.regional_copy, out_path,
                                 include_transcript=body.include_transcript,
                                 copies=body.copies)
    if not result.get("ok"):
        return JSONResponse(status_code=503, content=result)
    result["download_url"] = f"/api/pdf/{filename}"
    result.pop("path", None)
    return result


@app.get("/api/pdf/{filename}")
def download_pdf(filename: str):
    if "/" in filename or "\\" in filename or not filename.endswith(".pdf"):
        raise HTTPException(400, "invalid filename")
    path = os.path.join(PDF_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, "PDF not found or expired")
    return FileResponse(path, media_type="application/pdf", filename=filename)


# ------------------------------------------------------------------ CRUD
@app.post("/api/complaints")
def create_complaint(body: ComplaintIn):
    payload = body.model_dump()
    payload["regional_language"] = (payload.get("regional_language")
                                    or config.region_language(payload["police_region"]))
    saved = database.save_complaint(payload)
    return {"ok": True, "complaint": saved}


@app.get("/api/complaints")
def get_complaints(q: str = "", limit: int = 100):
    return {"complaints": database.list_complaints(q, limit), "stats": database.stats()}


@app.get("/api/complaints/{complaint_id}")
def get_complaint(complaint_id: int):
    complaint = database.get_complaint(complaint_id)
    if not complaint:
        raise HTTPException(404, "complaint not found")
    return complaint


@app.put("/api/complaints/{complaint_id}")
def update_complaint(complaint_id: int, body: UpdateComplaintIn):
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    if not changes:
        raise HTTPException(400, "no changes supplied")
    updated = database.update_complaint(complaint_id, changes)
    if not updated:
        raise HTTPException(404, "complaint not found")
    return {"ok": True, "complaint": updated}


@app.delete("/api/complaints/{complaint_id}")
def delete_complaint(complaint_id: int):
    if not database.delete_complaint(complaint_id):
        raise HTTPException(404, "complaint not found")
    return {"ok": True, "deleted": complaint_id}


@app.get("/api/stats")
def get_stats():
    return database.stats()


# ------------------------------------------------------------- static frontend
if os.path.isdir(config.FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
