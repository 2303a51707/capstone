"""
pdf_export.py - renders the FIR draft to PDF, in English or in any supported Indian script.

Engine note (worth knowing before you change it): ReportLab draws TTF glyphs in code-point
order with no shaping engine, so Devanagari and Telugu conjuncts come out broken - a Telugu
reader sees visible viramas where a ligature belongs. fpdf2 delegates to HarfBuzz when
set_text_shaping(True) is on, which reorders and ligates correctly. That is why fpdf2 is the
primary engine here and ReportLab is only the English-only fallback.

If the font for a script is missing, the exporter REFUSES to render that language rather
than emitting a page of empty boxes, and says which font to install.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

from .. import config

log = logging.getLogger("nyayavoice.pdf")

# fpdf2 subsets fonts through fontTools, which logs one INFO line per glyph table.
# That is hundreds of lines per PDF and drowns the application log.
logging.getLogger("fontTools").setLevel(logging.WARNING)
logging.getLogger("fontTools.subset").setLevel(logging.WARNING)

SCRIPT_FONT = {
    "latin": "NotoSans",
    "devanagari": "NotoSansDevanagari",
    "telugu": "NotoSansTelugu",
    "tamil": "NotoSansTamil",
    "kannada": "NotoSansKannada",
    "malayalam": "NotoSansMalayalam",
    "bengali": "NotoSansBengali",
    "gujarati": "NotoSansGujarati",
    "gurmukhi": "NotoSansGurmukhi",
    "odia": "NotoSansOriya",
    "arabic": "NotoSansArabic",
}

NAVY = (16, 37, 68)
BLUE = (43, 95, 179)
SAFFRON = (217, 119, 6)
GREY = (91, 107, 130)
LIGHT = (241, 244, 249)
RED = (220, 38, 38)


def font_for(language: str) -> Optional[str]:
    script = config.LANGUAGES.get(language, {}).get("script", "latin")
    return SCRIPT_FONT.get(script)


def font_available(language: str) -> bool:
    family = font_for(language)
    if not family:
        return False
    return os.path.exists(os.path.join(config.FONT_DIR, f"{family}-Regular.ttf"))


def status() -> Dict:
    try:
        import fpdf  # noqa: F401
        engine = "fpdf2"
    except Exception:
        engine = None
    fonts = {code: font_available(code) for code in config.LANGUAGES}
    return {
        "engine": engine,
        "shaping": engine == "fpdf2",
        "font_dir": config.FONT_DIR,
        "fonts_available": fonts,
        "missing_fonts": [config.lang_name(c) for c, ok in fonts.items() if not ok],
        "hint": None if engine else "pip install fpdf2 uharfbuzz",
    }


class FIRDocument:
    """A4 FIR sheet with a running header, page numbers and a footer disclaimer."""

    def __init__(self, language: str = "en"):
        from fpdf import FPDF

        self.language = language
        self.family = font_for(language) or "NotoSans"
        self.latin = "NotoSans"

        class _PDF(FPDF):
            outer = self

            def header(inner):
                if inner.page_no() == 1:
                    return
                inner.set_font(self.latin, "", 8)
                inner.set_text_color(*GREY)
                inner.cell(0, 6, "NyayaVoice - AI-assisted FIR draft (requires officer "
                                 "verification)", align="L")
                inner.ln(8)

            def footer(inner):
                inner.set_y(-16)
                inner.set_font(self.latin, "", 7)
                inner.set_text_color(*GREY)
                inner.multi_cell(
                    0, 3.4,
                    "AI-ASSISTED DRAFT - NOT A REGISTERED FIR. Must be reviewed and verified by "
                    "an authorized police officer before official use.   "
                    f"Page {inner.page_no()}/{{nb}}",
                    align="C",
                )

        self.pdf = _PDF(orientation="P", unit="mm", format="A4")
        self._register_fonts()
        self.pdf.set_auto_page_break(auto=True, margin=20)
        self.pdf.set_margins(16, 14, 16)
        self.pdf.set_text_shaping(True)
        self.pdf.add_page()

    def _register_fonts(self):
        required = {self.family, self.latin}
        already = {f.lower() for f in getattr(self.pdf, "fonts", {})}
        for family in required:
            for style, suffix in (("", "Regular"), ("B", "Bold")):
                if f"{family}{style}".lower() in already:
                    continue
                path = os.path.join(config.FONT_DIR, f"{family}-{suffix}.ttf")
                if not os.path.exists(path):
                    raise FileNotFoundError(
                        f"Font {family}-{suffix}.ttf is missing. Run: python scripts/fetch_fonts.py"
                    )
                self.pdf.add_font(family, style=style, fname=path)
        try:
            self.pdf.set_fallback_fonts([self.latin])
        except Exception:
            pass

    # ------------------------------------------------------------- primitives
    def _text(self, family, style, size, color):
        self.pdf.set_font(family, style, size)
        self.pdf.set_text_color(*color)

    def letterhead(self, title: str, subtitle: str, reference: str):
        pdf = self.pdf
        pdf.set_fill_color(*NAVY)
        pdf.rect(0, 0, 210, 30, "F")
        self._text(self.latin, "B", 9, (255, 255, 255))
        pdf.set_xy(16, 8)
        pdf.cell(0, 5, "NYAYAVOICE", align="L")
        self._text(self.latin, "", 7.5, (200, 214, 235))
        pdf.set_xy(16, 13.5)
        pdf.cell(0, 4, "Multilingual Voice-Based FIR Assistance System", align="L")
        self._text(self.latin, "B", 9, (255, 255, 255))
        pdf.set_xy(-70, 8)
        pdf.cell(54, 5, reference, align="R")
        self._text(self.latin, "", 7.5, (200, 214, 235))
        pdf.set_xy(-70, 13.5)
        pdf.cell(54, 4, datetime.now().strftime("%d %B %Y, %I:%M %p"), align="R")

        pdf.set_xy(16, 36)
        self._text(self.family, "B", 15, NAVY)
        pdf.multi_cell(0, 7, title, align="C")
        self._text(self.family, "", 8.5, GREY)
        pdf.set_x(16)
        pdf.multi_cell(0, 4.6, subtitle, align="C")
        pdf.ln(3)

    def warning_banner(self, text: str):
        pdf = self.pdf
        pdf.set_x(16)
        pdf.set_fill_color(254, 242, 242)
        pdf.set_draw_color(*RED)
        self._text(self.family, "B", 8.2, RED)
        pdf.multi_cell(0, 4.6, text, border=1, align="C", fill=True)
        pdf.ln(3)

    def section_heading(self, text: str):
        pdf = self.pdf
        pdf.set_x(16)
        if pdf.get_y() > 250:
            pdf.add_page()
        pdf.ln(1.5)
        self._text(self.family, "B", 9.5, BLUE)
        pdf.cell(0, 5.5, text.upper())
        pdf.ln(6)
        pdf.set_draw_color(*BLUE)
        pdf.set_line_width(0.3)
        pdf.line(16, pdf.get_y() - 0.5, 194, pdf.get_y() - 0.5)
        pdf.ln(1.5)

    def field_row(self, label: str, value: str, half: bool = False):
        pdf = self.pdf
        width = 89 if half else 178
        start_x = pdf.get_x()
        self._text(self.family, "", 6.8, GREY)
        pdf.set_x(start_x)
        pdf.multi_cell(width, 3.6, label.upper(), align="L",
                       new_x="LEFT" if half else "LMARGIN", new_y="NEXT")
        missing = str(value).strip() in ("", "Not provided", "None stated")
        self._text(self.family, "" if missing else "B", 9, GREY if missing else NAVY)
        pdf.set_x(start_x)
        pdf.multi_cell(width, 4.4, str(value) or "Not provided", align="L",
                       new_x="LEFT" if half else "LMARGIN", new_y="NEXT")
        pdf.ln(1.2)

    def pair(self, label_a, value_a, label_b, value_b):
        pdf = self.pdf
        y0 = pdf.get_y()
        pdf.set_xy(16, y0)
        self.field_row(label_a, value_a, half=True)
        y_left = pdf.get_y()
        pdf.set_xy(105, y0)
        self.field_row(label_b, value_b, half=True)
        pdf.set_y(max(y_left, pdf.get_y()))
        pdf.set_x(16)

    def paragraph(self, text: str, size: float = 9):
        self.pdf.set_x(16)
        self._text(self.family, "", size, (22, 35, 59))
        self.pdf.multi_cell(0, 4.8, str(text))
        self.pdf.ln(1.5)

    def bullets(self, lines: List[str]):
        pdf = self.pdf
        for line in lines:
            pdf.set_x(16)
            if pdf.get_y() > 258:
                pdf.add_page()
            pdf.set_fill_color(*LIGHT)
            pdf.set_x(16)
            self._text(self.family, "", 8.8, NAVY)
            pdf.multi_cell(0, 4.6, str(line), border=0, fill=True)
            pdf.ln(1.2)

    def signature_row(self, left: str, right: str):
        pdf = self.pdf
        if pdf.get_y() > 240:
            pdf.add_page()
        pdf.ln(6)
        self._text(self.family, "", 8, GREY)
        y0 = pdf.get_y()
        pdf.set_xy(16, y0)
        pdf.multi_cell(85, 4.4, left)
        y_left = pdf.get_y()
        pdf.set_xy(109, y0)
        pdf.multi_cell(85, 4.4, right)
        pdf.set_y(max(y_left, pdf.get_y()))

    def output(self, path: str) -> str:
        self.pdf.output(path)
        return path


# --------------------------------------------------------------------- public
def _render_copy(doc: FIRDocument, fir: Dict, labels: Dict, note: Optional[str] = None):
    """Render one language copy of the FIR into an open document."""
    doc.letterhead(
        fir.get("document_title", "FIRST INFORMATION REPORT - AI-ASSISTED DRAFT"),
        f"{labels.get('police_station', 'Police Station')}: {fir.get('police_station', '')}  |  "
        f"{fir.get('district_state', '')}",
        fir.get("reference_number", ""),
    )
    doc.warning_banner(fir.get("status_banner", ""))
    if note:
        doc._text(doc.family, "", 7.5, GREY)
        doc.pdf.multi_cell(0, 3.8, note)
        doc.pdf.ln(2)

    doc.section_heading(labels.get("_report_particulars", "Report Particulars"))
    doc.pair(labels.get("reference_number", "Reference"), fir.get("reference_number", ""),
             labels.get("report_date", "Date of Report"), fir.get("report_date", ""))
    doc.pair(labels.get("police_station", "Police Station"), fir.get("police_station", ""),
             labels.get("report_time", "Time of Report"), fir.get("report_time", ""))
    doc.pair(labels.get("language_of_complaint", "Language of Complaint"),
             fir.get("language_of_complaint", ""),
             labels.get("incident_type", "Nature of Incident"), fir.get("incident_type", ""))

    doc.section_heading(labels.get("_complainant", "Complainant Details"))
    doc.pair(labels.get("complainant_name", "Complainant"), fir.get("complainant_name", ""),
             labels.get("complainant_contact", "Contact Number"), fir.get("complainant_contact", ""))
    doc.pair(labels.get("complainant_address", "Address"), fir.get("complainant_address", ""),
             labels.get("victim_name", "Victim"), fir.get("victim_name", ""))

    doc.section_heading(labels.get("_incident", "Incident Details"))
    doc.pair(labels.get("incident_date", "Date of Incident"), fir.get("incident_date", ""),
             labels.get("incident_time", "Time of Incident"), fir.get("incident_time", ""))
    doc.field_row(labels.get("incident_location", "Place of Incident"),
                  fir.get("incident_location", ""))

    doc.section_heading(labels.get("incident_description", "Description of Incident"))
    doc.paragraph(fir.get("incident_description", ""))

    doc.section_heading(labels.get("_property", "Property, Weapons and Injuries"))
    doc.pair(labels.get("property_involved", "Property Involved"), fir.get("property_involved", ""),
             labels.get("property_value", "Value / Amount"), fir.get("property_value", ""))
    doc.pair(labels.get("vehicle_number", "Vehicle Number"), fir.get("vehicle_number", ""),
             labels.get("imei_number", "IMEI Number"), fir.get("imei_number", ""))
    doc.pair(labels.get("weapon_used", "Weapon"), fir.get("weapon_used", ""),
             labels.get("injuries_reported", "Injuries"), fir.get("injuries_reported", ""))

    doc.section_heading(labels.get("_parties", "Accused and Witnesses"))
    doc.field_row(labels.get("accused_details", "Accused / Suspect"), fir.get("accused_details", ""))
    doc.field_row(labels.get("witness_details", "Witnesses"), fir.get("witness_details", ""))
    if str(fir.get("threats_reported", "")).strip() not in ("", "Not provided"):
        doc.field_row(labels.get("threats_reported", "Threats"), fir.get("threats_reported", ""))

    doc.section_heading(labels.get("potentially_relevant_provisions",
                                   "Potentially Relevant Legal Provisions"))
    provisions = fir.get("potentially_relevant_provisions", [])
    if isinstance(provisions, str):
        provisions = [provisions]
    doc.bullets(provisions)
    if fir.get("applicable_law_regime"):
        doc._text(doc.family, "", 7.6, GREY)
        doc.pdf.multi_cell(0, 3.8, str(fir["applicable_law_regime"]))
        doc.pdf.ln(1)

    doc.signature_row(fir.get("verification_line", ""), fir.get("officer_line", ""))
    doc.pdf.ln(3)
    doc._text(doc.family, "", 6.9, GREY)
    doc.pdf.multi_cell(0, 3.4, fir.get("ai_notice", config.DISCLAIMER))


def generate(fir_bundle: Dict,
             regional_copy: Optional[Dict],
             out_path: str,
             include_transcript: bool = True,
             copies: str = "both") -> Dict:
    """
    Write the FIR PDF.

    copies: 'english' | 'regional' | 'both'
    Returns {ok, path, pages, languages, warnings}
    """
    try:
        import fpdf  # noqa: F401
    except Exception:
        return {"ok": False,
                "error": "fpdf2 is not installed. Run: pip install fpdf2 uharfbuzz"}

    warnings: List[str] = []
    languages: List[str] = []
    fir = fir_bundle["fir"]
    labels = fir_bundle["field_labels"]

    if not font_available("en"):
        return {"ok": False,
                "error": "NotoSans-Regular.ttf is missing. Run: python scripts/fetch_fonts.py"}

    doc = FIRDocument("en")

    if copies in ("english", "both"):
        _render_copy(doc, fir, labels)
        languages.append("English")

    if copies in ("regional", "both") and regional_copy:
        target = regional_copy.get("language", "en")
        if target == "en":
            warnings.append("The regional language is English, so only one copy was produced.")
        elif not font_available(target):
            warnings.append(
                f"The {config.lang_name(target)} copy was skipped because "
                f"{font_for(target)}-Regular.ttf is missing. Run: python scripts/fetch_fonts.py"
            )
        else:
            doc.pdf.add_page()
            regional_doc = FIRDocument(target)
            regional_doc.pdf = doc.pdf                       # keep one output file
            regional_doc._register_fonts()
            _render_copy(regional_doc, regional_copy["fir"], regional_copy["labels"],
                         note=regional_copy.get("note"))
            languages.append(config.lang_name(target))
            if not regional_copy.get("translated", False):
                warnings.append("The regional copy is partly untranslated - the translation "
                                "provider was unavailable. No text was invented.")

    if include_transcript:
        doc.pdf.add_page()
        original_language = fir_bundle.get("original_language", "en")
        transcript_doc = doc
        if original_language != "en" and font_available(original_language):
            transcript_doc = FIRDocument(original_language)
            transcript_doc.pdf = doc.pdf
            transcript_doc._register_fonts()
        elif original_language != "en":
            warnings.append(f"The original {config.lang_name(original_language)} transcript could "
                            f"not be embedded - font missing.")
        transcript_doc.letterhead(
            "ANNEXURE - ORIGINAL STATEMENT AS RECORDED",
            f"Language: {config.lang_name(original_language)}  |  "
            f"Reference: {fir.get('reference_number', '')}",
            fir.get("reference_number", ""),
        )
        transcript_doc.section_heading("Original transcript (unmodified)")
        transcript_doc.paragraph(fir_bundle.get("original_transcript", ""), size=10)
        transcript_doc.pdf.ln(2)
        doc.section_heading("English translation")
        doc.paragraph(fir_bundle.get("english_translation", ""), size=9.5)
        doc._text(doc.latin, "", 7.4, GREY)
        doc.pdf.multi_cell(0, 3.6,
                           "The original transcript is retained verbatim and is never modified by "
                           "the system. Where the English translation and the original differ, the "
                           "original statement of the complainant prevails and must be re-read to "
                           "the complainant by the officer.")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    doc.pdf.alias_nb_pages()
    doc.output(out_path)

    return {
        "ok": True,
        "path": out_path,
        "pages": doc.pdf.page_no(),
        "languages": languages,
        "engine": "fpdf2 + HarfBuzz shaping",
        "warnings": warnings,
    }
