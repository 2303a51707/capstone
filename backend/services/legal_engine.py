"""
legal_engine.py - identifies potentially relevant legal provisions from an English
complaint, and explains why each one was suggested.

Three independent signals are blended so that no single one can silently dominate:

  1. RULE LAYER      explainable phrase + element matching from crime_rules.json.
                     Produces the human-readable reason and the "facts detected" list.
  2. RETRIEVAL LAYER TF-IDF cosine similarity between the complaint and one document
                     per provision (offence title + statute text + keywords).
                     Handles short colloquial complaint text well.
  3. MODEL LAYER     the calibrated classifier trained on 40k court judgments.
                     Broad legal knowledge, but a different text domain, so it carries
                     the smallest weight and is shown as supporting evidence only.

Nothing here decides anything. Every result is labelled "potentially relevant" and
carries the signal breakdown so an officer can see exactly how it was produced.
"""
from __future__ import annotations

import functools
import json
import math
import os
import re
from typing import Dict, List, Optional

from .. import config

_KB: Dict = {}
_RULES: Dict = {}
_SHARED_ELEMENTS: Dict = {}
_RETRIEVAL = None
_CATEGORY_CLF = None
_CLASSIFIER = None
_METRICS: Dict = {}
_LOAD_ERRORS: List[str] = []


# --------------------------------------------------------------------- loading
def load():
    """Load the knowledge base and ML artefacts once, tolerating missing artefacts."""
    global _KB, _RULES, _SHARED_ELEMENTS, _RETRIEVAL, _CLASSIFIER, _CATEGORY_CLF, _METRICS
    if _KB:
        return

    with open(os.path.join(config.DATA_DIR, "legal_kb.json"), encoding="utf-8") as fh:
        _KB = json.load(fh)
    with open(os.path.join(config.DATA_DIR, "crime_rules.json"), encoding="utf-8") as fh:
        _RULES = json.load(fh)
    _SHARED_ELEMENTS = {e["id"]: e for e in _RULES.get("shared_elements", [])}

    try:
        import joblib
        path = os.path.join(config.ARTIFACT_DIR, "retrieval_index.joblib")
        if os.path.exists(path):
            _RETRIEVAL = joblib.load(path)
        else:
            _LOAD_ERRORS.append("retrieval_index.joblib not found - run backend/ml/train.py")
    except Exception as exc:                                    # pragma: no cover
        _LOAD_ERRORS.append(f"retrieval index unavailable: {exc}")

    try:
        import joblib
        path = os.path.join(config.ARTIFACT_DIR, "clf_pipeline.joblib")
        if os.path.exists(path):
            _CLASSIFIER = joblib.load(path)
        cpath = os.path.join(config.ARTIFACT_DIR, "category_clf.joblib")
        if os.path.exists(cpath):
            _CATEGORY_CLF = joblib.load(cpath).get("pipeline")
        mpath = os.path.join(config.ARTIFACT_DIR, "metrics.json")
        if os.path.exists(mpath):
            with open(mpath, encoding="utf-8") as fh:
                _METRICS = json.load(fh)
    except Exception as exc:                                    # pragma: no cover
        _LOAD_ERRORS.append(f"classifier unavailable: {exc}")


def status() -> Dict:
    load()
    return {
        "ipc_sections": len(_KB.get("ipc", {})),
        "extra_provisions": len(_KB.get("extra", {})),
        "crime_categories": len(_RULES.get("categories", [])),
        "retrieval_index": _RETRIEVAL is not None,
        "classifier": _CLASSIFIER is not None,
        "model_metrics": _METRICS,
        "warnings": _LOAD_ERRORS,
    }


def get_provision(code: str) -> Optional[Dict]:
    load()
    if code.startswith("IPC:"):
        return _KB["ipc"].get(code[4:])
    if code.startswith("X:"):
        return _KB["extra"].get(code[2:])
    return None


# ------------------------------------------------------------- text utilities
def _norm(text: str) -> str:
    text = str(text or "").lower()
    text = text.replace("₹", " rupees ").replace("rs.", "rupees").replace("rs ", "rupees ")
    text = re.sub(r"[^a-z0-9\s\-']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _snippet(haystack: str, needle: str, width: int = 60) -> str:
    """Pull the phrase back out of the original complaint so the UI can quote it."""
    idx = haystack.lower().find(needle.lower())
    if idx < 0:
        return needle
    start = max(0, idx - width // 3)
    end = min(len(haystack), idx + len(needle) + width)
    out = haystack[start:end].strip()
    if start > 0:
        out = "..." + out
    if end < len(haystack):
        out = out + "..."
    return out


@functools.lru_cache(maxsize=4096)
def _phrase_pattern(phrase: str):
    """Word-boundary matcher. Plain substring search is a trap here: without \b,
    'mob' matches inside 'mobile phone' and a phone theft gets classified as rioting."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])")


def _phrase_present(haystack: str, phrase: str) -> bool:
    return bool(_phrase_pattern(phrase).search(haystack))


def _hits(normalised: str, phrases: List[str]) -> List[str]:
    """Matched phrases, with shorter phrases dropped when a longer match covers them.

    Without this, "threatened to kill me" scores three times - as "threat",
    "threatened" and "threatened to kill" - and drowns out the real primary offence.
    """
    matched = [p for p in phrases if _norm(p) and _phrase_present(normalised, _norm(p))]
    matched.sort(key=len, reverse=True)
    kept: List[str] = []
    for phrase in matched:
        if not any(_norm(phrase) in _norm(longer) for longer in kept):
            kept.append(phrase)
    return kept


# ------------------------------------------------------------- element layer
def _detect_elements(category: Dict, normalised: str, original: str) -> Dict[str, Dict]:
    """Which ingredients of the offence can actually be seen in the complaint."""
    detected: Dict[str, Dict] = {}
    definitions = list(category.get("elements", []))
    definitions += [e for e in _SHARED_ELEMENTS.values()
                    if e["id"] not in {d["id"] for d in definitions}]
    for element in definitions:
        matched = _hits(normalised, element.get("any", []))
        if matched:
            detected[element["id"]] = {
                "id": element["id"],
                "label": element["label"],
                "matched_terms": matched[:4],
                "evidence": _snippet(original, matched[0]),
            }
    return detected


# ---------------------------------------------------------- crime classification
def classify(english_text: str) -> Dict:
    """Classify the complaint into incident categories with a confidence for each."""
    load()
    normalised = _norm(english_text)
    results = []
    for category in _RULES["categories"]:
        strong = _hits(normalised, category.get("strong", []))
        weak = _hits(normalised, category.get("weak", []))
        negative = _hits(normalised, category.get("negative", []))
        if not strong and not weak:
            continue
        elements = _detect_elements(category, normalised, english_text)
        own_ids = {e["id"] for e in category.get("elements", [])}
        own_elements = [e for e in elements if e in own_ids]
        # ingredients of the offence carry weight too: "iron rod" and "fracture" are
        # what turn a bare "beat me" into grievous hurt by a dangerous weapon
        raw = (1.0 * len(strong) + 0.35 * len(weak)
               + 0.25 * len(own_elements) - 0.9 * len(negative))
        if raw <= 0:
            continue
        # some categories are only meaningful if a defining ingredient is present:
        # "my bike is missing" is a theft report, not a missing-person report
        gate = category.get("requires_elements", [])
        if gate and not any(g in elements for g in gate):
            continue
        score = 1.0 - math.exp(-raw / 0.9)          # saturating, keeps 0..1
        results.append({
            "id": category["id"],
            "label": category["label"],
            "icon": category.get("icon", "file-text"),
            "score": round(score, 4),
            "confidence": int(round(score * 100)),
            "matched_strong": strong[:6],
            "matched_weak": weak[:6],
            "suppressed_by": negative[:3],
            "elements": elements,
            "advisory": category.get("advisory"),
            "_category": category,
        })
    results.sort(key=lambda r: r["score"], reverse=True)

    primary = results[0] if results else None
    return {
        "primary": {k: v for k, v in primary.items() if k != "_category"} if primary else None,
        "all": [{k: v for k, v in r.items() if k != "_category"} for r in results[:5]],
        "_ranked": results,
        "unclassified": not results,
    }


# ------------------------------------------------------------- signal layers
# Cosine similarity that counts as a full-strength match. Scaling against this fixed
# reference rather than against the best hit in the list matters: peak-normalising
# hands a score of 1.0 to the least-bad match even when nothing actually matched.
RETRIEVAL_FULL_MATCH = config.RETRIEVAL_FULL_MATCH
RETRIEVAL_FLOOR = float(os.environ.get("RETRIEVAL_FLOOR", 0.07))
MODEL_FULL_MATCH = config.MODEL_FULL_MATCH


def _retrieval_scores(english_text: str, top_n: int = 25) -> Dict[str, float]:
    if _RETRIEVAL is None:
        return {}
    from sklearn.metrics.pairwise import linear_kernel
    query = _RETRIEVAL["vectorizer"].transform([english_text.lower()])
    sims = linear_kernel(query, _RETRIEVAL["matrix"]).ravel()
    if sims.max() <= 0:
        return {}
    import numpy as np
    order = np.argsort(sims)[::-1][:top_n]
    return {
        _RETRIEVAL["codes"][i]: min(1.0, float(sims[i]) / RETRIEVAL_FULL_MATCH)
        for i in order if sims[i] >= RETRIEVAL_FLOOR
    }


def _category_model_scores(english_text: str) -> Dict[str, float]:
    """Category probabilities spread over the provisions of each category.

    The model's useful output is 'this reads like a theft', not 'this is exactly
    379'. Within the category the element layer picks the section, so every
    provision inherits the category probability scaled by its own weight - which
    orders the base provision first without overriding the element requirements.
    """
    if _CATEGORY_CLF is None:
        return {}
    try:
        import numpy as np
        proba = _CATEGORY_CLF.predict_proba([english_text.lower()])[0]
        classes = _CATEGORY_CLF.named_steps["clf"].classes_
        by_category = {classes[i]: float(proba[i]) for i in np.argsort(proba)[::-1][:3]
                       if proba[i] > 0.05}
        if not by_category:
            return {}
        scored = {}
        for category in _RULES["categories"]:
            probability = by_category.get(category["id"])
            if not probability:
                continue
            for provision in category["provisions"]:
                value = min(1.0, probability / MODEL_FULL_MATCH) * float(
                    provision.get("weight", 1.0))
                code = provision["code"]
                scored[code] = max(scored.get(code, 0.0), value)
        # Highest first, so the loop that can surface a provision on the model
        # alone sees the base provision of the category before its variants.
        return dict(sorted(scored.items(), key=lambda kv: kv[1], reverse=True))
    except Exception:                                            # pragma: no cover
        return {}


def _section_model_scores(english_text: str, top_n: int = 10) -> Dict[str, float]:
    if _CLASSIFIER is None:
        return {}
    try:
        import numpy as np
        proba = _CLASSIFIER.predict_proba([english_text.lower()])[0]
        classes = _CLASSIFIER.named_steps["clf"].classes_
        order = np.argsort(proba)[::-1][:top_n]
        return {f"IPC:{classes[i]}": min(1.0, float(proba[i]) / MODEL_FULL_MATCH)
                for i in order if proba[i] > 0.02}
    except Exception:                                            # pragma: no cover
        return {}


def _model_scores(english_text: str, top_n: int = 10) -> Dict[str, float]:
    """Category model when it is available, section model otherwise."""
    return _category_model_scores(english_text) or _section_model_scores(english_text, top_n)


# ------------------------------------------------------------- main entrypoint
def find_sections(english_text: str,
                  incident_date_iso: Optional[str] = None,
                  max_results: int = None) -> Dict:
    """Return a ranked list of potentially relevant provisions with full explanations."""
    load()
    max_results = max_results or config.MAX_PROVISIONS
    text = (english_text or "").strip()

    if len(text.split()) < 4:
        return {
            "provisions": [], "classification": None, "signals_used": [],
            "note": "The complaint is too short to analyse. Please describe what happened "
                    "in a few more words.",
            "law_regime": _law_regime(incident_date_iso),
        }

    normalised = _norm(text)
    classification = classify(text)
    retrieval = _retrieval_scores(text)
    model = _model_scores(text)

    candidates: Dict[str, Dict] = {}

    # ---- signal 1: rules -----------------------------------------------------
    for category in classification["_ranked"][:3]:
        cat_score = category["score"]
        if cat_score < 0.20:
            continue
        elements = category["elements"]
        for provision in category["_category"]["provisions"]:
            required = provision.get("requires", [])
            if required and not all(r in elements for r in required):
                continue
            code = provision["code"]
            rule_score = cat_score * provision.get("weight", 1.0)
            existing = candidates.get(code)
            if existing and existing["rule_score"] >= rule_score:
                continue
            supporting = [elements[r] for r in required if r in elements] or \
                         list(elements.values())[:3]
            candidates[code] = {
                "code": code,
                "rule_score": rule_score,
                "reason": provision["reason"],
                "category_id": category["id"],
                "category_label": category["label"],
                "facts": supporting,
            }

    # ---- signal 2 + 3: retrieval and the trained model -----------------------
    for code, score in list(retrieval.items())[:8]:
        if code not in candidates and score >= 0.80:
            candidates[code] = {
                "code": code, "rule_score": 0.0,
                "reason": "Surfaced by semantic similarity between the complaint and the "
                          "text of this provision, rather than by an explicit rule.",
                "category_id": None, "category_label": None, "facts": [],
            }
    for code, score in list(model.items())[:5]:
        if code not in candidates and score >= 0.90:
            candidates[code] = {
                "code": code, "rule_score": 0.0,
                "reason": ("Suggested by the offence-category model trained on court "
                           "judgments, without an explicit rule match. Treat this as a "
                           "lead to verify, not a conclusion."
                           if _CATEGORY_CLF is not None else
                           "Suggested by the statute-identification model trained on court "
                           "judgments. Treat this as a lead to verify, not a conclusion."),
                "category_id": None, "category_label": None, "facts": [],
            }

    # ---- blend ---------------------------------------------------------------
    results = []
    for code, cand in candidates.items():
        entry = get_provision(code)
        if not entry:
            continue
        r_score = cand["rule_score"]
        s_score = retrieval.get(code, 0.0)
        m_score = model.get(code, 0.0)
        final = (config.WEIGHT_RULES * r_score
                 + config.WEIGHT_RETRIEVAL * s_score
                 + config.WEIGHT_MODEL * m_score)
        floor = config.MIN_PROVISION_SCORE if r_score > 0 else config.MIN_UNRULED_SCORE
        if final < floor:
            continue
        results.append({
            **_display(entry, incident_date_iso),
            "score": round(final, 4),
            "confidence": int(round(min(final, 1.0) * 100)),
            "relevance": ("High" if final >= 0.55 else "Medium" if final >= 0.32 else "Low"),
            "matching_reason": cand["reason"],
            "matched_facts": cand["facts"],
            "incident_category": cand["category_label"],
            "signals": {
                "rule_layer": round(r_score, 3),
                "retrieval_layer": round(s_score, 3),
                "model_layer": round(m_score, 3),
                "weights": {
                    "rule": config.WEIGHT_RULES,
                    "retrieval": config.WEIGHT_RETRIEVAL,
                    "model": config.WEIGHT_MODEL,
                },
            },
            "reasoning_chain": _chain(text, cand, entry),
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:max_results]

    advisories = []
    for category in classification["_ranked"][:2]:
        if category.get("advisory"):
            advisories.append({"category": category["label"], "note": category["advisory"]})

    return {
        "provisions": results,
        "classification": classification["primary"],
        "alternative_classifications": classification["all"][1:4],
        "advisories": advisories,
        "law_regime": _law_regime(incident_date_iso),
        "signals_used": [
            {"name": "Rule layer", "available": True, "weight": config.WEIGHT_RULES},
            {"name": "Statute retrieval", "available": _RETRIEVAL is not None,
             "weight": config.WEIGHT_RETRIEVAL},
            {"name": "Trained classifier", "available": _CLASSIFIER is not None,
             "weight": config.WEIGHT_MODEL,
             "trained_on": _METRICS.get("n_rows_used"),
             "top3_accuracy": _METRICS.get("top3_accuracy")},
        ],
        "note": None if results else
        "No provision crossed the relevance threshold. The complaint has still been "
        "recorded in full and must be assessed by the duty officer.",
        "disclaimer": config.DISCLAIMER,
    }


# --------------------------------------------------------------- presentation
def _law_regime(incident_date_iso: Optional[str]) -> Dict:
    """Which code applies depends on the date of the offence, not the date of the report."""
    if not incident_date_iso:
        return {
            "applicable": "unknown",
            "note": "The date of the incident was not established. The BNS, 2023 applies to "
                    "offences committed on or after 1 July 2024; the IPC, 1860 continues to "
                    "apply to offences committed before that date. Confirm the date with the "
                    "complainant before finalising the sections.",
        }
    applicable = "BNS" if incident_date_iso >= config.BNS_CUTOVER else "IPC"
    return {
        "applicable": applicable,
        "incident_date": incident_date_iso,
        "note": (f"The incident date {incident_date_iso} falls "
                 f"{'on or after' if applicable == 'BNS' else 'before'} 1 July 2024, so the "
                 f"{'Bharatiya Nyaya Sanhita, 2023' if applicable == 'BNS' else 'Indian Penal Code, 1860'} "
                 f"applies."),
    }


_LAW_SHORT = {
    "Information Technology Act, 2000": "IT Act",
    "Motor Vehicles Act, 1988": "MV Act",
    "Protection of Children from Sexual Offences Act, 2012": "POCSO Act",
    "Protection of Women from Domestic Violence Act, 2005": "DV Act",
    "Dowry Prohibition Act, 1961": "Dowry Prohibition Act",
    "Arms Act, 1959": "Arms Act",
    "Bharatiya Nyaya Sanhita, 2023": "BNS",
}


def _short_law_name(law_name: str) -> str:
    if law_name in _LAW_SHORT:
        return _LAW_SHORT[law_name]
    if law_name.startswith("Bharatiya Nagarik Suraksha Sanhita"):
        return "BNSS"
    if law_name.startswith("Standard police procedure"):
        return "Police procedure"
    return law_name.split(",")[0]


def _display(entry: Dict, incident_date_iso: Optional[str]) -> Dict:
    """Build the citation the way an officer should write it: BNS first, IPC in brackets."""
    bns = entry.get("bns_section")
    status_ = entry.get("mapping_status")
    is_ipc = entry["code"].startswith("IPC:")

    if is_ipc and bns:
        primary_label = f"BNS Section {bns}"
        primary_law = "Bharatiya Nyaya Sanhita, 2023"
        legacy = f"IPC Section {entry['section_number']}"
        citation = f"Section {bns} BNS (formerly Section {entry['section_number']} IPC)"
        verify = ("BNS mapping is a curated working reference. Verify against the bare act "
                  "before charging.")
    elif is_ipc:
        primary_label = f"IPC Section {entry['section_number']}"
        primary_law = "Indian Penal Code, 1860"
        legacy = None
        citation = f"Section {entry['section_number']} IPC"
        verify = ("No verified BNS equivalent is recorded for this section. Identify the "
                  "corresponding BNS provision manually for an offence on or after 1 July 2024."
                  if status_ == "unmapped" else
                  "This offence was not re-enacted in the BNS, 2023.")
    else:
        short_law = _short_law_name(entry["law_name"])
        number = entry["section_number"]
        looks_numeric = bool(re.match(r"^[\d]", str(number)))
        primary_label = (f"{short_law} \u00a7 {number}" if looks_numeric else str(number))
        primary_law = entry["law_name"]
        legacy = None
        citation = (f"Section {number}, {short_law}" if looks_numeric
                    else f"{number} ({short_law})")
        verify = "Special or local law - verify the current text before charging."

    return {
        "code": entry["code"],
        "section_label": primary_label,
        "law_name": primary_law,
        "legacy_label": legacy,
        "citation": citation,
        "offence_name": entry.get("bns_offence_name") or entry["offence_name"],
        "legacy_offence_name": entry["offence_name"] if entry.get("bns_offence_name") else None,
        "description": entry["description"],
        "elements": entry.get("elements", []),
        "punishment": entry.get("punishment"),
        "mapping_status": status_,
        "verification_note": verify,
        "flag": entry.get("flag"),
        "training_cases": entry.get("n_training_cases", 0),
        "source": entry.get("source"),
    }


def _chain(text: str, cand: Dict, entry: Dict) -> List[Dict]:
    """The 'why did NyayaVoice suggest this' trace shown in the UI."""
    chain = []
    if cand["facts"]:
        chain.append({"step": "Complaint says", "value": cand["facts"][0]["evidence"]})
        chain.append({"step": "Detected", "value": ", ".join(f["label"] for f in cand["facts"][:3])})
    else:
        chain.append({"step": "Complaint says", "value": text[:140] + ("..." if len(text) > 140 else "")})
    if cand["category_label"]:
        chain.append({"step": "Incident category", "value": cand["category_label"]})
    chain.append({"step": "Legal concept", "value": entry["offence_name"]})
    chain.append({"step": "Potential provision", "value": entry["code"].replace("IPC:", "IPC ")
                  .replace("X:", ""), "final": True})
    return chain