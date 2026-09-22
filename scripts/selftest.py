"""
selftest.py - checks every component and tells you exactly what is missing.

Run:  python scripts/selftest.py

Exits 0 if the core pipeline works, 1 if something required is broken. Optional
components (Whisper, translation, spaCy) report as warnings, because the app is
designed to degrade honestly rather than fail when they are absent.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

OK, WARN, FAIL = "  OK  ", " WARN ", " FAIL "
results = []


def check(name, fn, required=True):
    try:
        detail = fn()
        results.append((OK, name, detail or ""))
        return True
    except Exception as exc:
        results.append((FAIL if required else WARN, name, f"{type(exc).__name__}: {exc}"))
        return False


def main():
    print("NyayaVoice self-test\n" + "=" * 74)

    # ---------------------------------------------------------- knowledge base
    def kb():
        from backend.services import legal_engine
        status = legal_engine.status()
        if status["ipc_sections"] < 100:
            raise RuntimeError("legal_kb.json looks incomplete - run backend/ml/build_kb.py")
        return (f"{status['ipc_sections']} IPC sections, "
                f"{status['extra_provisions']} special-law provisions, "
                f"{status['crime_categories']} crime categories")
    check("Legal knowledge base", kb)

    def retrieval():
        from backend.services import legal_engine
        if not legal_engine.status()["retrieval_index"]:
            raise RuntimeError("retrieval_index.joblib missing - run backend/ml/train.py")
        return "statute retrieval index loaded"
    check("Retrieval index", retrieval)

    def classifier():
        from backend.services import legal_engine
        status = legal_engine.status()
        if not status["classifier"]:
            raise RuntimeError("clf_pipeline.joblib missing - run backend/ml/train.py")
        m = status["model_metrics"]
        return (f"{m.get('n_classes')} classes, top-1 {m.get('top1_accuracy')}, "
                f"top-3 {m.get('top3_accuracy')}, top-5 {m.get('top5_accuracy')}")
    check("Trained classifier", classifier, required=False)

    # ---------------------------------------------------------------- pipeline
    def pipeline():
        from backend.services import legal_engine, nlp_engine, fir_builder
        text = ("Yesterday evening near Charminar my mobile phone worth Rs. 5,000 was "
                "stolen from my pocket by an unknown person.")
        entities = nlp_engine.extract(text)
        legal = legal_engine.find_sections(text, entities["resolved_iso_date"])
        if not legal["provisions"]:
            raise RuntimeError("no provisions found for a plain theft complaint")
        top = legal["provisions"][0]
        if "303" not in top["section_label"] and "379" not in str(top.get("legacy_label")):
            raise RuntimeError(f"unexpected top provision: {top['section_label']}")
        bundle = fir_builder.build(text, text, entities["entities"], legal["provisions"],
                                   legal["classification"], "en", "Telangana")
        if not bundle["fir"]["potentially_relevant_provisions"]:
            raise RuntimeError("the FIR draft contains no provisions block")
        return (f"theft -> {top['section_label']} ({top['confidence']}%), "
                f"{sum(1 for v in entities['entities'].values() if v)} entities extracted")
    core_ok = check("End-to-end analysis pipeline", pipeline)

    # --------------------------------------------------------------------- PDF
    def pdf():
        import tempfile
        from backend.services import pdf_export, legal_engine, nlp_engine, fir_builder
        status = pdf_export.status()
        if not status["engine"]:
            raise RuntimeError("fpdf2 not installed - pip install fpdf2 uharfbuzz")
        missing = status["missing_fonts"]
        text = "My bike was stolen from outside my office yesterday."
        entities = nlp_engine.extract(text)
        legal = legal_engine.find_sections(text)
        bundle = fir_builder.build(text, text, entities["entities"], legal["provisions"],
                                   legal["classification"], "en", "Telangana")
        out = os.path.join(tempfile.gettempdir(), "nyayavoice_selftest.pdf")
        result = pdf_export.generate(bundle, None, out, copies="english")
        if not result["ok"]:
            raise RuntimeError(result.get("error"))
        note = f", fonts missing for: {', '.join(missing)}" if missing else ", all Indic fonts present"
        return f"{result['pages']}-page PDF written{note}"
    check("PDF export", pdf)

    # ---------------------------------------------------------------- database
    def db():
        from backend import database, config
        database.init()
        database.stats()
        return os.path.basename(config.DB_PATH)
    check("Database", db)

    # ------------------------------------------------------------- optional
    def speech():
        from backend.services import asr
        status = asr.status()
        if not status["available"]:
            raise RuntimeError(status["error"].split(".")[0])
        return f"{status['backend']} ({status['model']})"
    check("Speech recognition (server-side)", speech, required=False)

    def translate():
        from backend.services import translation
        status = translation.provider_status()
        if not status["available"]:
            raise RuntimeError("no provider loaded: " + "; ".join(status["errors"])[:110])
        out = translation.translate("My phone was stolen near the market.", "en", "hi")
        if not out["translated"]:
            raise RuntimeError(out.get("error", "translation returned unchanged text"))
        return f"{status['active_provider']}: {out['text'][:46]}"
    check("Translation provider", translate, required=False)

    def spacy_check():
        from backend.services import nlp_engine
        if not nlp_engine._load_spacy():
            raise RuntimeError("spaCy model not installed (rules-only extraction is in use)")
        return "en_core_web_sm loaded"
    check("spaCy (optional name/place extraction)", spacy_check, required=False)

    # ----------------------------------------------------------------- report
    print()
    for level, name, detail in results:
        print(f"[{level}] {name:<38} {detail}")

    failures = [r for r in results if r[0] == FAIL]
    warnings = [r for r in results if r[0] == WARN]
    print("\n" + "=" * 74)
    if failures:
        print(f"{len(failures)} required component(s) failed. The app will not run correctly.")
        print("Most common fix:  python backend/ml/build_kb.py --csv <dataset.csv>")
        print("              and python backend/ml/train.py    --csv <dataset.csv>")
        sys.exit(1)
    print("Core pipeline is working.")
    if warnings:
        print(f"{len(warnings)} optional component(s) unavailable - the app degrades honestly:")
        for _, name, detail in warnings:
            print(f"   - {name}: {detail}")
        print("\n  Speech    : pip install faster-whisper   (the browser path works without it)")
        print("  Translate : pip install deep-translator   (needs internet)")
        print("  spaCy     : pip install spacy && python -m spacy download en_core_web_sm")
    sys.exit(0 if core_ok else 1)


if __name__ == "__main__":
    main()
