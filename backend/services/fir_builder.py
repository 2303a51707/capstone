"""
fir_builder.py - assembles the FIR draft.

Two hard rules, enforced structurally rather than by prompt discipline:

  1. Every value in the draft comes from an extracted entity or from the complainant's
     own transcript. There is no generative step that could invent a witness, a time,
     or an accused. Anything absent renders as "Not provided" and stays editable.

  2. The identified provisions are written INTO the FIR body, cited BNS-first with the
     IPC section in brackets, each carrying its confidence and the fact that it is an
     AI suggestion awaiting officer verification.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from .. import config
from . import translation

NOT_PROVIDED = "Not provided"


def _value(entities: Dict, key: str, default: str = NOT_PROVIDED) -> str:
    field = entities.get(key)
    if not field:
        return default
    value = field.get("value") if isinstance(field, dict) else field
    return str(value).strip() if value not in (None, "") else default


def reference_number(seq: Optional[int] = None) -> str:
    year = datetime.now().year
    tail = f"{seq:04d}" if seq is not None else uuid.uuid4().hex[:4].upper()
    return f"NV-{year}-{tail}"


def _provisions_block(provisions: List[Dict]) -> List[str]:
    """The sections, written the way they should appear on the FIR face sheet."""
    if not provisions:
        return ["No provision could be identified with sufficient confidence from the "
                "statement. To be determined by the duty officer."]
    lines = []
    for i, p in enumerate(provisions, 1):
        legacy = f" [formerly {p['legacy_label']}]" if p.get("legacy_label") else ""
        flag = ""
        if p.get("flag") == "NO_OFFENCE_DISCLOSED":
            flag = " - NOTE: no cognizable offence disclosed on the facts stated"
        elif p.get("flag") == "PROCEDURAL":
            flag = " - procedural provision, not an offence"
        elif p.get("flag") == "MANDATORY_SPECIAL_HANDLING":
            flag = " - MANDATORY special-law handling"
        lines.append(
            f"{i}. {p['section_label']}{legacy} - {p['offence_name']} "
            f"({p['relevance']} relevance, {p['confidence']}% match){flag}"
        )
    return lines


def _narrative(transcript_english: str, entities: Dict, category: Optional[str]) -> str:
    """The incident description: the complainant's own account, framed as their statement."""
    head = "The complainant states as follows:"
    body = transcript_english.strip()
    if not body.endswith((".", "!", "?")):
        body += "."
    tail = []
    location = _value(entities, "location", "")
    when_date = _value(entities, "incident_date", "")
    when_time = _value(entities, "incident_time", "")
    if location or when_date or when_time:
        parts = []
        if when_date:
            parts.append(f"date stated as {when_date}")
        if when_time:
            parts.append(f"time stated as {when_time}")
        if location:
            parts.append(f"place stated as {location}")
        tail.append("Particulars as stated: " + "; ".join(parts) + ".")
    tail.append("The above is a transcription and translation of the complainant's oral "
                "statement. It has been neither verified nor investigated.")
    return f"{head}\n\n\"{body}\"\n\n" + " ".join(tail)


def build(transcript_original: str,
          transcript_english: str,
          entities: Dict,
          provisions: List[Dict],
          classification: Optional[Dict],
          original_language: str,
          police_region: str,
          police_station: Optional[str] = None,
          reference: Optional[str] = None,
          law_regime: Optional[Dict] = None,
          summary: Optional[str] = None) -> Dict:
    """Build the English FIR draft as an ordered dict of labelled fields."""
    now = datetime.now()
    regional_language = config.region_language(police_region)
    category_label = (classification or {}).get("label")

    fir = {
        "document_title": "FIRST INFORMATION REPORT - AI-ASSISTED DRAFT",
        "status_banner": "DRAFT - NOT A REGISTERED FIR. Requires verification and signature "
                         "by an authorized police officer before official use.",
        "police_station": police_station or f"{police_region} (station to be assigned)",
        "district_state": police_region,
        "reference_number": reference or reference_number(),
        "report_date": now.strftime("%d %B %Y"),
        "report_time": now.strftime("%I:%M %p"),
        "language_of_complaint": config.lang_name(original_language),
        "language_of_this_copy": "English",
        "regional_copy_language": config.lang_name(regional_language),

        "complainant_name": _value(entities, "complainant_name"),
        "complainant_contact": _value(entities, "mobile_number"),
        "complainant_address": NOT_PROVIDED,
        "victim_name": _value(entities, "victim_name", "Same as complainant, unless stated otherwise"),

        "incident_type": category_label or "To be determined by the officer",
        "incident_date": _value(entities, "incident_date"),
        "incident_time": _value(entities, "incident_time"),
        "incident_location": _value(entities, "location"),

        "incident_description": _narrative(transcript_english, entities, category_label),
        "officer_summary": summary or "",

        "property_involved": _value(entities, "property_involved"),
        "property_value": _value(entities, "money_involved"),
        "vehicle_number": _value(entities, "vehicle_number"),
        "imei_number": _value(entities, "imei"),
        "weapon_used": _value(entities, "weapon"),
        "injuries_reported": _value(entities, "injuries"),
        "threats_reported": _value(entities, "threats"),

        "accused_details": _value(entities, "accused_name", "Unknown / not identified by the complainant"),
        "witness_details": _value(entities, "witnesses", "None stated"),

        "potentially_relevant_provisions": _provisions_block(provisions),
        "applicable_law_regime": (law_regime or {}).get("note", ""),

        "additional_information": NOT_PROVIDED,
        "officer_remarks": "",
        "verification_line": "Read over to the complainant in their own language and admitted "
                             "to be correct: ______________________  (complainant's signature)",
        "officer_line": "Recorded and verified by: ______________________  "
                        "(name, rank, number of the officer)    Date: ____/____/________",
        "ai_notice": "Sections 'incident description', 'extracted particulars' and "
                     "'potentially relevant provisions' were prepared with AI assistance from "
                     "the complainant's spoken statement. " + config.DISCLAIMER,
    }

    field_labels = {
        "police_station": "Police Station", "district_state": "District / State",
        "reference_number": "Reference Number", "report_date": "Date of Report",
        "report_time": "Time of Report", "language_of_complaint": "Language of Complaint",
        "complainant_name": "Complainant", "complainant_contact": "Contact Number",
        "complainant_address": "Address", "victim_name": "Victim",
        "incident_type": "Nature of Incident", "incident_date": "Date of Incident",
        "incident_time": "Time of Incident", "incident_location": "Place of Incident",
        "incident_description": "Description of Incident", "officer_summary": "Summary",
        "property_involved": "Property Involved", "property_value": "Value / Amount",
        "vehicle_number": "Vehicle Number", "imei_number": "IMEI Number",
        "weapon_used": "Weapon", "injuries_reported": "Injuries",
        "threats_reported": "Threats", "accused_details": "Accused / Suspect",
        "witness_details": "Witnesses",
        "potentially_relevant_provisions": "Potentially Relevant Legal Provisions "
                                           "(AI-suggested, for officer verification)",
        "applicable_law_regime": "Applicable Code", "additional_information": "Additional Information",
        "officer_remarks": "Officer Remarks",
    }

    missing = [field_labels.get(k, k) for k, v in fir.items()
               if isinstance(v, str) and v == NOT_PROVIDED]

    return {
        "fir": fir,
        "field_labels": field_labels,
        "editable_fields": list(field_labels.keys()),
        "missing_fields": missing,
        "regional_language": regional_language,
        "regional_language_name": config.lang_name(regional_language),
        "original_language": original_language,
        "original_transcript": transcript_original,
        "english_translation": transcript_english,
        "generated_at": now.isoformat(timespec="seconds"),
    }


TRANSLATABLE = [
    "document_title", "status_banner", "incident_type", "incident_date", "incident_time",
    "incident_location", "incident_description", "officer_summary", "property_involved",
    "property_value", "weapon_used", "injuries_reported", "threats_reported",
    "accused_details", "witness_details", "potentially_relevant_provisions",
    "applicable_law_regime", "additional_information", "verification_line", "officer_line",
    "ai_notice", "complainant_name", "victim_name", "complainant_address",
]


def build_regional(fir_bundle: Dict, target_language: Optional[str] = None) -> Dict:
    """Produce the police station's regional-language copy of the same draft."""
    target = target_language or fir_bundle["regional_language"]
    fir = fir_bundle["fir"]

    if target == "en":
        return {"fir": dict(fir), "labels": dict(fir_bundle["field_labels"]),
                "language": "en", "language_name": "English", "translated": False,
                "note": "The police station's working language is English, so this copy is "
                        "identical to the English draft."}

    subset = {k: v for k, v in fir.items() if k in TRANSLATABLE}
    result = translation.translate_fir(subset, "en", target)

    translated_fir = dict(fir)
    translated_fir.update(result["fir"])

    label_keys = list(fir_bundle["field_labels"].keys())
    label_results = translation.translate_many(
        [fir_bundle["field_labels"][k] for k in label_keys], "en", target)
    labels = {k: r["text"] for k, r in zip(label_keys, label_results)}

    return {
        "fir": translated_fir,
        "labels": labels,
        "language": target,
        "language_name": config.lang_name(target),
        "translated": result["translated"],
        "provider": result.get("provider"),
        "partial_failures": result.get("partial_failures", 0),
        "note": ("Machine translation of the English draft. Section numbers, names, amounts "
                 "and identifiers are preserved unchanged. The English copy governs in case "
                 "of any discrepancy."
                 if result["translated"] else
                 "Translation was unavailable, so some fields below are still in English. "
                 "They have NOT been altered or invented."),
    }
