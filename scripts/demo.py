"""
demo.py - runs the whole pipeline on the command line, without the browser.

    python scripts/demo.py                    # run all built-in sample complaints
    python scripts/demo.py --index 3          # run one of them
    python scripts/demo.py --text "..." --language ml --region Telangana
    python scripts/demo.py --index 0 --pdf out.pdf

Useful for a viva or a screenshot in the project report: it shows the translation,
the extracted entities, the classification, and the provisions with their signal
breakdown, all in one screen.
"""
import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from backend import config                                        # noqa: E402
from backend.services import (asr, fir_builder, legal_engine,     # noqa: E402
                              nlp_engine, pdf_export, translation)

SAMPLES = [
    {"language": "ml", "region": "Telangana", "label": "Kerala tourist robbed in Hyderabad",
     "text": "ഇന്നലെ വൈകുന്നേരം ചാർമിനാറിന് അടുത്ത് വെച്ച് എന്റെ മൊബൈൽ ഫോണും 5000 രൂപയും "
             "ആരോ എന്റെ പോക്കറ്റിൽ നിന്ന് മോഷ്ടിച്ചു. എന്റെ പേര് അനിൽ കുമാർ."},
    {"language": "te", "region": "Telangana", "label": "Chain snatching, Hyderabad",
     "text": "నిన్న రాత్రి 8 గంటలకు అమీర్‌పేట బస్ స్టాప్ దగ్గర బైక్ మీద వచ్చిన ఇద్దరు వ్యక్తులు "
             "నా మెడలోని బంగారు గొలుసు లాక్కొని పారిపోయారు. గొలుసు విలువ 80,000 రూపాయలు."},
    {"language": "hi", "region": "Karnataka", "label": "Online fraud, Hindi speaker in Bengaluru",
     "text": "मुझे बैंक से फोन आया था, उसने OTP मांगा और मेरे खाते से 45,000 रुपये कट गए। "
             "मेरा नाम राजेश शर्मा है, मेरा नंबर 9876543210 है।"},
    {"language": "en", "region": "Telangana", "label": "Assault with a weapon",
     "text": "My neighbour Ramesh beat me with an iron rod outside my house yesterday evening "
             "around 6 pm. I have a fracture in my left arm and I am admitted in Gandhi Hospital. "
             "He also threatened to kill me. My friend Vijay saw everything."},
    {"language": "ta", "region": "Tamil Nadu", "label": "House-breaking, Tamil speaker",
     "text": "நேற்று இரவு நாங்கள் வெளியூர் சென்றிருந்தபோது யாரோ எங்கள் வீட்டின் பூட்டை உடைத்து "
             "நகைகளையும் பணத்தையும் திருடிச் சென்றுவிட்டார்கள்."},
    {"language": "en", "region": "Telangana", "label": "Lost property - no offence disclosed",
     "text": "I lost my Aadhaar card, PAN card and driving licence somewhere near Sultan Bazaar "
             "this morning. I do not know where they fell. I need a report for duplicates."},
]

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
BLUE, GREEN, YELLOW = "\033[34m", "\033[32m", "\033[33m"


def rule(char="-"):
    print(DIM + char * 78 + RESET)


def run(text, language, region, station=None, pdf_path=None, as_json=False):
    detection = translation.detect_language(text)
    source = language or detection["language"]

    if source == "en":
        english = text
        translation_result = {"translated": False, "note": "already in English"}
    else:
        translation_result = translation.translate(text, source, "en")
        english = translation_result["text"]

    extraction = nlp_engine.extract(english, report_date=date.today())
    legal = legal_engine.find_sections(english, extraction["resolved_iso_date"])
    classification = legal["classification"]
    summary = nlp_engine.summarise(english, extraction["entities"],
                                   (classification or {}).get("label"))

    bundle = fir_builder.build(text, english, extraction["entities"], legal["provisions"],
                               classification, source, region, station,
                               law_regime=legal["law_regime"], summary=summary)
    regional = fir_builder.build_regional(bundle)

    if as_json:
        print(json.dumps({
            "original": text, "language": source, "english": english,
            "entities": {k: v["value"] for k, v in extraction["entities"].items() if v},
            "classification": classification, "provisions": legal["provisions"],
            "fir": bundle["fir"],
        }, ensure_ascii=False, indent=2))
        return

    rule("=")
    print(f"{BOLD}ORIGINAL ({config.lang_name(source)}){RESET}")
    print(f"  {text}")
    print(f"\n{BOLD}ENGLISH TRANSLATION{RESET}  "
          f"{DIM}[{translation_result.get('provider') or translation_result.get('note')}]{RESET}")
    if not translation_result.get("translated") and source != "en":
        print(f"  {YELLOW}! NOT TRANSLATED - {translation_result.get('error', '')[:70]}{RESET}")
    print(f"  {english}")

    print(f"\n{BOLD}EXTRACTED INFORMATION{RESET}")
    for key, field in extraction["entities"].items():
        marker = f"{GREEN}+{RESET}" if field else f"{DIM}-{RESET}"
        value = field["value"] if field else f"{DIM}Not provided{RESET}"
        print(f"  {marker} {key:<20} {value}")
    if extraction["follow_up_questions"]:
        print(f"\n  {DIM}Officer should still ask:{RESET}")
        for question in extraction["follow_up_questions"][:4]:
            print(f"    {DIM}. {question}{RESET}")

    print(f"\n{BOLD}CLASSIFICATION{RESET}")
    if classification:
        print(f"  {BLUE}{classification['label']}{RESET}  ({classification['confidence']}% confidence)")
    else:
        print(f"  {YELLOW}Could not be classified - for the duty officer to determine{RESET}")

    print(f"\n{BOLD}POTENTIALLY RELEVANT LEGAL PROVISIONS{RESET}")
    if not legal["provisions"]:
        print(f"  {YELLOW}None reached the confidence threshold.{RESET}")
    for i, p in enumerate(legal["provisions"], 1):
        legacy = f"  (formerly {p['legacy_label']})" if p.get("legacy_label") else ""
        print(f"\n  {i}. {BOLD}{p['section_label']}{RESET}{DIM}{legacy}{RESET}")
        print(f"     {p['offence_name']}")
        print(f"     {p['relevance']} relevance, {p['confidence']}%   "
              f"{DIM}rule {p['signals']['rule_layer']:.2f} | "
              f"retrieval {p['signals']['retrieval_layer']:.2f} | "
              f"model {p['signals']['model_layer']:.2f}{RESET}")
        print(f"     {DIM}Why: {p['matching_reason']}{RESET}")
        for fact in p.get("matched_facts", [])[:3]:
            print(f"       {GREEN}v{RESET} {fact['label']}  {DIM}\"{fact['evidence'][:58]}\"{RESET}")

    print(f"\n{BOLD}APPLICABLE CODE{RESET}\n  {legal['law_regime']['note']}")

    print(f"\n{BOLD}FIR DRAFT - SECTIONS AS THEY APPEAR IN THE DOCUMENT{RESET}")
    for line in bundle["fir"]["potentially_relevant_provisions"]:
        print(f"  {line}")
    print(f"\n  {DIM}Reference {bundle['fir']['reference_number']} | "
          f"regional copy: {regional['language_name']} "
          f"({'translated' if regional['translated'] else 'NOT translated'}){RESET}")
    if bundle["missing_fields"]:
        print(f"  {DIM}Left blank (never invented): {', '.join(bundle['missing_fields'][:8])}{RESET}")

    if pdf_path:
        result = pdf_export.generate(bundle, regional, pdf_path, copies="both")
        print(f"\n{BOLD}PDF{RESET}  " + (f"{GREEN}{pdf_path}{RESET} "
              f"({result['pages']} pages, {', '.join(result['languages'])})"
              if result["ok"] else f"{YELLOW}{result.get('error')}{RESET}"))
        for warning in result.get("warnings", []):
            print(f"  {YELLOW}! {warning}{RESET}")
    rule("=")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text")
    parser.add_argument("--language", help="source language code, e.g. ml, te, hi")
    parser.add_argument("--region", default="Telangana")
    parser.add_argument("--station")
    parser.add_argument("--index", type=int, help="run a single built-in sample")
    parser.add_argument("--pdf", help="also write a PDF to this path")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--audio", help="transcribe an audio file first")
    args = parser.parse_args()

    if args.audio:
        with open(args.audio, "rb") as fh:
            result = asr.transcribe(fh.read(), args.language,
                                    os.path.splitext(args.audio)[1])
        if not result["ok"]:
            sys.exit(f"Transcription failed: {result['error']}")
        print(f"Transcribed ({result['language_name']}): {result['text']}\n")
        run(result["text"], result["language"], args.region, args.station, args.pdf, args.json)
        return

    if args.text:
        run(args.text, args.language, args.region, args.station, args.pdf, args.json)
        return

    samples = [SAMPLES[args.index]] if args.index is not None else SAMPLES
    provider = translation.provider_status()
    if not provider["available"]:
        print(f"{YELLOW}Note: no translation provider is loaded, so the non-English samples "
              f"below will show untranslated text. Install one with: "
              f"pip install deep-translator{RESET}\n")
    for sample in samples:
        print(f"\n{BOLD}{BLUE}### {sample['label']}{RESET}")
        run(sample["text"], sample["language"], sample["region"],
            pdf_path=args.pdf, as_json=args.json)


if __name__ == "__main__":
    main()
