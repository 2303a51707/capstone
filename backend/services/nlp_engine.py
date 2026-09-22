"""
nlp_engine.py - pulls the facts out of an English complaint.

Design rule that overrides everything else in this file: NEVER INVENT A VALUE.
Every extracted field carries the exact span it came from. If a field cannot be
grounded in the complainant's own words it is returned as null and the UI renders
"Not provided" with an editable box. A confident-looking blank is safer than a
plausible fabrication in a document that goes into a police file.

spaCy is used for person and place names when it is installed; the regex layer
below is the fallback and always runs.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

_NLP = None
_SPACY_TRIED = False

MONTHS = ("january february march april may june july august september october "
          "november december jan feb mar apr jun jul aug sep sept oct nov dec").split()

WEAPONS = ["knife", "gun", "pistol", "revolver", "sword", "axe", "sickle", "iron rod",
           "rod", "stick", "stone", "blade", "hammer", "acid", "chilli powder", "bottle",
           "firearm", "katta", "machete", "bat"]

PROPERTY_ITEMS = [
    "mobile phone", "mobile", "phone", "smartphone", "iphone", "laptop", "tablet",
    "purse", "wallet", "handbag", "bag", "backpack", "gold chain", "chain", "necklace",
    "bangles", "earrings", "ring", "jewellery", "jewelry", "ornaments", "watch",
    "bicycle", "cycle", "bike", "motorcycle", "scooter", "scooty", "car", "auto",
    "cash", "money", "documents", "passport", "aadhaar card", "aadhaar", "pan card",
    "driving licence", "driving license", "atm card", "debit card", "credit card",
    "cheque book", "sim card", "certificate", "marksheet", "buffalo", "cattle", "goat",
    "tractor", "generator", "cables", "television", "tv", "fridge", "camera",
]

INJURY_TERMS = ["injured", "injury", "injuries", "bleeding", "wound", "wounded", "fracture",
                "fractured", "broken", "swelling", "bruise", "unconscious", "stitches",
                "hospital", "hospitalised", "hospitalized", "admitted", "treatment",
                "burn", "burns", "pain", "icu", "surgery", "operation"]

THREAT_TERMS = ["threatened", "threat", "will kill", "kill me", "will not spare", "warned",
                "abused", "abuse", "intimidated", "see you outside", "finish you",
                "death threat", "blackmail", "blackmailed"]

RELATION_WORDS = ("husband wife son daughter brother sister father mother friend neighbour "
                  "neighbor colleague landlord tenant driver servant maid boss employee "
                  "uncle aunt cousin in-law relative boyfriend girlfriend").split()

NAME_STOPWORDS = {
    "i", "me", "my", "he", "she", "they", "we", "it", "the", "a", "an", "sir", "madam",
    "police", "station", "yesterday", "today", "tomorrow", "morning", "evening", "night",
    "afternoon", "please", "help", "complaint", "fir", "rupees", "phone", "mobile",
    "not", "no", "yes", "and", "but", "then", "when", "while", "after", "before",
}


def _load_spacy():
    global _NLP, _SPACY_TRIED
    if _SPACY_TRIED:
        return _NLP
    _SPACY_TRIED = True
    try:
        import spacy
        for model in ("en_core_web_trf", "en_core_web_sm"):
            try:
                _NLP = spacy.load(model)
                break
            except Exception:
                continue
    except Exception:
        _NLP = None
    return _NLP


def _field(value, evidence=None, source="regex", confidence="medium"):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return {"value": value, "evidence": evidence, "source": source, "confidence": confidence}


VERB_LIKE = {
    "was", "is", "were", "are", "has", "have", "had", "did", "does", "said", "told",
    "came", "went", "saw", "took", "gave", "beat", "hit", "with", "and", "from", "near",
    "also", "then", "but", "who", "that", "which", "while", "when", "after", "before",
}


def _clean_name_candidate(raw: str) -> str:
    """Trim a regex capture down to the part that is actually a name.

    'My neighbour Ramesh beat me' -> 'Ramesh'. The patterns capture generously
    because Indian names vary in length; the trimming happens here instead.
    """
    if not raw:
        return ""
    words = [w.strip(".,;:") for w in raw.split() if w.strip(".,;:")]
    while words and (words[0].lower() in NAME_STOPWORDS
                     or words[0].lower() in RELATION_WORDS
                     or words[0].lower() in VERB_LIKE
                     or not words[0][0].isupper()):
        words.pop(0)
    while words and (words[-1].lower() in VERB_LIKE
                     or words[-1].lower() in NAME_STOPWORDS
                     or not words[-1][0].isupper()):
        words.pop()
    return " ".join(words[:3])


def _is_name(raw: str) -> bool:
    """A name is one to three capitalised word-like tokens and no verbs."""
    if not raw:
        return False
    words = raw.split()
    if not 1 <= len(words) <= 3:
        return False
    for word in words:
        lowered = word.lower().strip(".,")
        if lowered in NAME_STOPWORDS or lowered in VERB_LIKE or len(lowered) < 2:
            return False
        if not word[0].isupper():
            return False
    return True


def _titlecase_name(raw: str) -> str:
    return " ".join(w.capitalize() for w in raw.split())


# ------------------------------------------------------------------ extractors
def _extract_names(text: str) -> Dict:
    out: Dict[str, Optional[Dict]] = {"complainant": None, "accused": None, "victim": None}

    patterns_self = [
        r"\bmy name is ([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+){0,3})",
        r"\bi am ([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+){1,3})\b",
        r"\bthis is ([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+){1,3}) (?:speaking|here)",
        r"\bmyself ([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+){0,3})",
    ]
    for pattern in patterns_self:
        m = re.search(pattern, text, re.I)
        candidate = _clean_name_candidate(m.group(1)) if m else ""
        if _is_name(candidate):
            out["complainant"] = _field(_titlecase_name(candidate), m.group(0), confidence="high")
            break

    patterns_accused = [
        r"\b(?:accused|suspect) (?:is |named )?([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+){0,2})",
        r"\b([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+){0,2}) (?:beat|hit|threatened|attacked|cheated|assaulted|abused) (?:me|my|him|her|us)\b",
        r"\bby (?:one |a person named )([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+){0,2})",
        r"\b(?:threatened|beaten|assaulted|attacked|cheated|harassed|abused|robbed|"
        r"molested|stalked|kidnapped) by ([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+){0,2})",
        r"\bmy (?:neighbour|neighbor|husband|colleague|landlord|tenant|boss)[, ]+([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+){0,2})",
    ]
    for pattern in patterns_accused:
        m = re.search(pattern, text, re.I)
        candidate = _clean_name_candidate(m.group(1)) if m else ""
        if _is_name(candidate):
            out["accused"] = _field(_titlecase_name(candidate), m.group(0))
            break

    m = re.search(r"\bmy (" + "|".join(RELATION_WORDS) + r")\b[, ]*(?:named |called )?"
                  r"([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)?)?", text)
    victim_candidate = _clean_name_candidate(m.group(2)) if (m and m.group(2)) else ""
    if _is_name(victim_candidate):
        out["victim"] = _field(f"{_titlecase_name(victim_candidate)} ({m.group(1).lower()} of complainant)",
                               m.group(0))

    nlp = _load_spacy()
    if nlp:
        doc = nlp(text)
        people = [e.text.strip() for e in doc.ents
                  if e.label_ == "PERSON" and e.text.strip().lower() not in NAME_STOPWORDS]
        if people and not out["accused"]:
            unused = [p for p in people
                      if not out["complainant"] or p.lower() != out["complainant"]["value"].lower()]
            if unused:
                out["accused"] = _field(_titlecase_name(unused[0]),
                                        f"named in the complaint: {unused[0]}", source="spacy")
    return out


def _extract_location(text: str) -> Optional[Dict]:
    patterns = [
        r"\b(?:near|at|in front of|outside|inside|beside|opposite)\s+((?:[A-Z][\w\-]+\s?){1,4}(?:road|street|nagar|colony|market|temple|station|bus stop|circle|junction|park|mall|hospital|college|school|bank|atm|hotel|complex|area|chowk|gate|bazaar)?)",
        r"\b(?:at|in|near)\s+([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+){0,3})\b",
        r"\bplace(?: of (?:the )?incident)?(?: is|:)?\s+([A-Z][\w\s,\-]{3,50})",
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            candidate = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
            if len(candidate) < 3:
                continue
            if candidate.split()[0].lower() in NAME_STOPWORDS:
                continue
            return _field(candidate, m.group(0))

    nlp = _load_spacy()
    if nlp:
        doc = nlp(text)
        places = [e.text.strip() for e in doc.ents if e.label_ in ("GPE", "LOC", "FAC")]
        if places:
            return _field(", ".join(dict.fromkeys(places[:3])), "place names in the complaint",
                          source="spacy")
    return None


def _extract_datetime(text: str, report_date: date) -> Dict:
    lowered = text.lower()
    date_field = None
    resolved_iso = None
    derivation = None

    explicit = re.search(
        r"\b(\d{1,2})[\s\-/.](\d{1,2}|" + "|".join(MONTHS) + r")[\s\-/.](\d{2,4})\b", lowered)
    if explicit:
        raw = explicit.group(0)
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y",
                    "%d/%m/%y", "%d-%m-%y"):
            try:
                parsed = datetime.strptime(raw.replace("  ", " ").strip(), fmt).date()
                resolved_iso = parsed.isoformat()
                date_field = _field(parsed.strftime("%d %B %Y"), raw, confidence="high")
                derivation = "stated explicitly by the complainant"
                break
            except ValueError:
                continue
        if not date_field:
            date_field = _field(raw, raw)

    if not date_field:
        relative = {
            "day before yesterday": 2, "yesterday": 1, "last night": 1, "today": 0,
            "this morning": 0, "this afternoon": 0, "this evening": 0, "tonight": 0,
            "last week": 7, "a week ago": 7, "last month": 30,
        }
        for phrase, delta in relative.items():
            if phrase in lowered:
                resolved = report_date - timedelta(days=delta)
                resolved_iso = resolved.isoformat()
                date_field = _field(
                    f"{phrase.capitalize()} ({resolved.strftime('%d %B %Y')})", phrase)
                derivation = (f"'{phrase}' resolved against the reporting date "
                              f"{report_date.strftime('%d %B %Y')} - confirm with the complainant")
                break
        else:
            m = re.search(r"\b(\d{1,2}) days? (?:ago|back|before)\b", lowered)
            if m:
                resolved = report_date - timedelta(days=int(m.group(1)))
                resolved_iso = resolved.isoformat()
                date_field = _field(f"{m.group(0)} ({resolved.strftime('%d %B %Y')})", m.group(0))
                derivation = "computed from the reporting date - confirm with the complainant"

    time_field = None
    clock = re.search(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm|a\.m\.|p\.m\.)?\b", lowered)
    if clock:
        time_field = _field(clock.group(0).strip(), clock.group(0), confidence="high")
    else:
        around = re.search(r"\baround (\d{1,2})\s*(am|pm|o'clock)?\b", lowered)
        if around:
            time_field = _field(around.group(0).strip(), around.group(0))
        else:
            for part in ("early morning", "morning", "afternoon", "evening", "night",
                         "midnight", "noon", "dawn", "dusk"):
                if part in lowered:
                    time_field = _field(f"{part.capitalize()} (approximate)", part,
                                        confidence="low")
                    break

    return {"date": date_field, "time": time_field,
            "resolved_iso_date": resolved_iso, "date_derivation": derivation}


def _extract_money(text: str) -> List[Dict]:
    found = []
    for m in re.finditer(
        r"(?:₹|rs\.?|inr|rupees)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lakhs|crore|crores|thousand|k)?",
        text, re.I
    ):
        amount = m.group(1).replace(",", "")
        try:
            value = float(amount)
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        multiplier = {"lakh": 1e5, "lakhs": 1e5, "crore": 1e7, "crores": 1e7,
                      "thousand": 1e3, "k": 1e3}.get(unit, 1)
        total = value * multiplier
        found.append({"value": f"Rs. {total:,.0f}".replace(".0", ""), "amount": total,
                      "evidence": m.group(0).strip()})
    for m in re.finditer(r"\b([\d,]+(?:\.\d+)?)\s*(lakh|lakhs|crore|crores)\s*(?:rupees)?\b",
                         text, re.I):
        amount = float(m.group(1).replace(",", ""))
        multiplier = 1e5 if m.group(2).lower().startswith("lakh") else 1e7
        total = amount * multiplier
        if not any(abs(f["amount"] - total) < 1 for f in found):
            found.append({"value": f"Rs. {total:,.0f}".replace(".0", ""), "amount": total,
                          "evidence": m.group(0).strip()})
    return found


def _extract_list(text: str, terms: List[str], label_map=None) -> List[Dict]:
    lowered = text.lower()
    out, seen = [], set()
    for term in sorted(terms, key=len, reverse=True):
        if re.search(r"\b" + re.escape(term) + r"\b", lowered):
            canonical = (label_map or {}).get(term, term)
            if canonical in seen:
                continue
            # skip a shorter term already covered by a longer one ("phone" inside "mobile phone")
            if any(term in s for s in seen):
                continue
            seen.add(canonical)
            idx = lowered.find(term)
            out.append({"value": canonical.title() if canonical.islower() else canonical,
                        "evidence": text[max(0, idx - 25): idx + len(term) + 25].strip()})
    return out


def _extract_contacts(text: str) -> Dict:
    phone = re.search(r"\b(?:\+91[\-\s]?)?([6-9]\d{9})\b", text)
    vehicle = re.search(
        r"\b([A-Z]{2}[\s\-]?\d{1,2}[\s\-]?[A-Z]{0,3}[\s\-]?\d{3,4})\b", text.upper())
    imei = re.search(r"\b(\d{15})\b", text)
    return {
        "mobile_number": _field(phone.group(1), phone.group(0), confidence="high") if phone else None,
        "vehicle_number": _field(re.sub(r"[\s\-]", "", vehicle.group(1)), vehicle.group(0),
                                 confidence="high") if vehicle else None,
        "imei": _field(imei.group(1), imei.group(0), confidence="high") if imei else None,
    }


def _extract_witnesses(text: str) -> List[Dict]:
    out = []
    for pattern in [
        r"\b((?:my |the )?(?:friend|neighbour|neighbor|shopkeeper|watchman|guard|colleague|brother|sister|wife|husband|driver|auto driver)[a-zA-Z\s]{0,20})\s+(?:saw|was with me|witnessed|was present|can confirm|also saw)",
        r"\b(?:witness(?:es)? (?:is|are|was|were)?|in the presence of)\s+"
        r"([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+){0,2})",
        r"\b([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)?)\s+(?:saw|witnessed) (?:the incident|everything|it)",
    ]:
        for m in re.finditer(pattern, text, re.I):
            value = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
            value = re.split(r"\b(?:and|was|were|saw|who|that|when)\b", value)[0].strip(" ,.")
            lowered = value.lower()
            if len(value) > 2 and not any(lowered in w["value"].lower()
                                          or w["value"].lower() in lowered for w in out):
                out.append({"value": value, "evidence": m.group(0).strip()})
    return out


# --------------------------------------------------------------------- public
def extract(english_text: str, report_date: Optional[date] = None) -> Dict:
    """Extract every supported entity from the English complaint text."""
    text = (english_text or "").strip()
    report_date = report_date or date.today()

    names = _extract_names(text)
    when = _extract_datetime(text, report_date)
    contacts = _extract_contacts(text)
    money = _extract_money(text)
    property_items = _extract_list(text, PROPERTY_ITEMS)
    weapons = _extract_list(text, WEAPONS)
    injuries = _extract_list(text, INJURY_TERMS)
    threats = _extract_list(text, THREAT_TERMS)
    witnesses = _extract_witnesses(text)

    entities = {
        "complainant_name": names["complainant"],
        "victim_name": names["victim"],
        "accused_name": names["accused"],
        "location": _extract_location(text),
        "incident_date": when["date"],
        "incident_time": when["time"],
        "mobile_number": contacts["mobile_number"],
        "vehicle_number": contacts["vehicle_number"],
        "imei": contacts["imei"],
        "money_involved": _field(", ".join(m["value"] for m in money),
                                 "; ".join(m["evidence"] for m in money)) if money else None,
        "property_involved": _field(", ".join(p["value"] for p in property_items),
                                    property_items[0]["evidence"]) if property_items else None,
        "weapon": _field(", ".join(w["value"] for w in weapons),
                         weapons[0]["evidence"]) if weapons else None,
        "injuries": _field(", ".join(i["value"] for i in injuries),
                           injuries[0]["evidence"]) if injuries else None,
        "threats": _field(", ".join(t["value"] for t in threats),
                          threats[0]["evidence"]) if threats else None,
        "witnesses": _field("; ".join(w["value"] for w in witnesses),
                            witnesses[0]["evidence"]) if witnesses else None,
    }

    provided = {k: v for k, v in entities.items() if v}
    missing = [k for k, v in entities.items() if not v]

    return {
        "entities": entities,
        "resolved_iso_date": when["resolved_iso_date"],
        "date_derivation": when["date_derivation"],
        "n_extracted": len(provided),
        "missing_fields": missing,
        "follow_up_questions": _follow_ups(missing, entities),
        "extractor": "spacy + rules" if _load_spacy() else "rules only",
    }


def _follow_ups(missing: List[str], entities: Dict) -> List[str]:
    """What the officer should still ask - never filled in automatically."""
    prompts = {
        "complainant_name": "What is your full name and address?",
        "incident_date": "On what date did this happen?",
        "incident_time": "At approximately what time did this happen?",
        "location": "Where exactly did this happen? Please give a landmark.",
        "accused_name": "Do you know who did this, or can you describe them?",
        "witnesses": "Was anyone else present who saw what happened?",
        "mobile_number": "What is a contact number where you can be reached?",
    }
    out = [prompts[f] for f in missing if f in prompts]
    if entities.get("property_involved") and not entities.get("money_involved"):
        out.append("What is the approximate value of the property involved?")
    if entities.get("vehicle_number") is None and entities.get("property_involved") and \
            re.search(r"bike|car|scooter|motorcycle|vehicle",
                      str(entities["property_involved"]["value"]), re.I):
        out.append("What is the registration number of the vehicle?")
    return out[:6]


def summarise(english_text: str, entities: Dict, category_label: Optional[str]) -> str:
    """A factual restatement built only from what the complainant actually said."""
    def val(key):
        field = entities.get(key)
        return field["value"] if field else None

    bits = []
    who = val("complainant_name")
    bits.append(f"The complainant{f' ({who})' if who else ''} reports")
    core = []
    if category_label:
        core.append(f"an incident of the nature of {category_label.lower()}")
    if val("property_involved"):
        core.append(f"involving {val('property_involved').lower()}")
    if val("money_involved"):
        core.append(f"and a sum of {val('money_involved')}")
    bits.append(" ".join(core) if core else "an incident")
    if val("location"):
        bits.append(f"at {val('location')}")
    when = " ".join(filter(None, [val("incident_date"), val("incident_time")]))
    if when:
        bits.append(f"on {when}")
    sentence = " ".join(bits).strip() + "."
    extras = []
    if val("accused_name"):
        extras.append(f"The person named is {val('accused_name')}.")
    if val("injuries"):
        extras.append(f"Injuries are reported: {val('injuries').lower()}.")
    if val("weapon"):
        extras.append(f"A weapon is mentioned: {val('weapon').lower()}.")
    if val("witnesses"):
        extras.append(f"Witnesses mentioned: {val('witnesses')}.")
    extras.append("This summary restates only what the complainant said; it has not been verified.")
    return " ".join([sentence] + extras)
