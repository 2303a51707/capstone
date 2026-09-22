# NyayaVoice

**Multilingual Voice-Based FIR Writer and Relevant Legal Section Finder using NLP**

A citizen speaks a complaint in their own language. NyayaVoice transcribes it, translates
it to English, extracts the facts, identifies potentially relevant legal provisions, and
produces an editable FIR draft in **English and the working language of the police station**.

```
Citizen's language  →  Speech recognition  →  Native-language text
                    →  English translation →  NLP + entity extraction
                    →  Crime classification →  Legal provision finder
                    →  FIR draft  ──┬── English copy
                                    └── Regional-language copy  →  PDF
```

The system is an **AI-assisted drafting aid**. It does not register FIRs, does not decide
what offence was committed, and never fills in a fact the complainant did not state.

---

## Quick start

```bash
# 1. Setup: installs dependencies, fetches fonts, builds the knowledge base, trains the model
./run.sh setup /path/to/indian_ipc_statute_identification.csv

# 2. Start
./run.sh start            # http://localhost:8000   (API docs at /docs)

# 3. Check everything is working
./run.sh test
```

Windows, or if you prefer doing it by hand:

```bash
python -m venv .venv && .venv\Scripts\activate      # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python scripts/fetch_fonts.py
python backend/ml/build_kb.py --csv indian_ipc_statute_identification.csv
python backend/ml/train.py    --csv indian_ipc_statute_identification.csv
uvicorn backend.app:app --reload --port 8000
```

Try it without the browser:

```bash
python scripts/demo.py                 # runs six sample complaints in five languages
python scripts/demo.py --index 1 --pdf out.pdf
python scripts/demo.py --text "എന്റെ ഫോൺ മോഷ്ടിക്കപ്പെട്ടു" --language ml --region Telangana
```

---

## What each dependency actually buys you

The app is built so that **every optional piece can be missing and the system still tells
you the truth about what it could and could not do**. Nothing is faked to keep the demo
looking smooth.

| Component | Package | Without it |
|---|---|---|
| Legal engine, FIR, PDF, database | in `requirements.txt` core | — required |
| Server-side speech | `faster-whisper` | The browser's Web Speech API still handles voice in Chrome/Edge. Auto-detect of spoken language needs Whisper. |
| Translation | `deep-translator` (needs internet) or `torch`+`transformers` for IndicTrans2/NLLB (offline after first download) | Non-English complaints are shown **untranslated and clearly flagged**. Nothing is invented. |
| Better name/place extraction | `spacy` + `en_core_web_sm` | Falls back to the regex layer, which handles most complaint phrasing. |
| Indic PDF output | `python scripts/fetch_fonts.py` | The regional-language PDF copy is **skipped with a message**, not rendered as empty boxes. |

---

## How the legal section finder works

This is the part of the project worth explaining in a viva, because the obvious approach
does not work well and the reason is interesting.

### The dataset

`indian_ipc_statute_identification.csv` holds **40,001 rows**: `case_facts` (court judgment
text with the statute reference masked as `[STATUTE]`), `ipc_section`, and `statute_text`.
It covers **320 distinct IPC sections**.

`backend/ml/build_kb.py` parses it into a structured knowledge base — offence name,
statutory text, ingredients of the offence, punishment, keywords — and adds:

* **6 IPC sections** the dataset does not cover but complaints commonly need
  (34, 120B, 143, 354A sexual harassment, 354C voyeurism, 354D stalking), taken from the bare act;
* **18 special-law and BNS-native provisions** — IT Act 66C/66D/66E/67, MV Act 134/184,
  POCSO, DV Act, Dowry Prohibition Act, Arms Act, BNS 304 snatching, BNS 103(2) mob lynching,
  BNS 111/112 organised crime, and procedural entries for missing-person and lost-property reports.

**326 IPC sections + 18 special provisions = 344 searchable provisions.**

### Why the trained model is not the decision-maker

Training a TF-IDF + calibrated LinearSVC on the judgments gives:

| Metric | Score |
|---|---|
| Top-1 accuracy | 14.6% |
| Top-3 accuracy | 38.0% |
| Top-5 accuracy | 50.8% |

(60 classes with ≥100 examples, 37,681 rows, held-out 20% split. The trained artifact is
11.5 MB — `ensemble=False` calibration keeps one fitted estimator rather than one per fold,
and float32 coefficients halve it again. The naive configuration produced a 98 MB file for
the same accuracy.)

That looks disappointing until you look at what the model is being asked to do. The
`case_facts` are **bail orders and judgments** — averaging 2,000 characters of formal court
prose, often citing several sections at once, with the target section masked out. A spoken
citizen complaint is 200 characters of colloquial speech. Those are **two different text
domains**, and a classifier trained on one does not transfer cleanly to the other.

So the model is used as *one* signal, not *the* answer. The engine blends three:

| Signal | Weight | What it contributes |
|---|---|---|
| **Rule layer** | 50% | 25 crime categories with trigger phrases and offence ingredients. Produces the plain-language reason and the "facts detected" list. High precision on the complaint types citizens actually report. |
| **Statute retrieval** | 32% | TF-IDF cosine similarity between the complaint and one document per provision (offence title ×3 + statutory text + keywords + everyday trigger vocabulary). Handles short colloquial text well. |
| **Trained classifier** | 18% | The 40k-judgment model. Broad legal coverage, wrong domain, so it is supporting evidence only. |

Weights live in `backend/config.py` and can be changed without touching code.

Every suggestion the UI shows carries its **per-signal breakdown**, so a user can see
whether a section came from an explicit rule, from text similarity, or from the model.

### Two bugs worth mentioning in the report

Both were found by testing on realistic complaints rather than on the dataset:

1. **Substring matching.** The word `mob` matched inside `mobile phone`, so a phone theft
   was being classified as **rioting**. Fixed by matching on word boundaries
   (`legal_engine._phrase_pattern`).
2. **Peak normalisation.** Retrieval scores were divided by the best score in the list, which
   handed a perfect 1.0 to the least-bad match even when nothing really matched — a lost-Aadhaar
   complaint was surfacing the Motor Vehicles Act. Fixed by scaling against a fixed reference
   similarity instead (`RETRIEVAL_FULL_MATCH`).

### Current law: IPC → BNS

The IPC was replaced by the **Bharatiya Nyaya Sanhita, 2023** for offences committed on or
after **1 July 2024**. Showing a raw IPC number as current law would be wrong, so:

* `backend/data/ipc_bns_map.json` carries **117 curated mappings** (302→103, 379→303(2),
  420→318(4), 498A→85, 506→351(2), …) with the offence title for each.
* Citations are rendered **BNS-first with the IPC section in brackets** — the form a court
  expects: *"Section 303(2) BNS (formerly Section 379 IPC)"*.
* Sections with no verified mapping are **flagged as unmapped**, not guessed.
* IPC 377 is marked as having no BNS equivalent — it was not re-enacted.
* BNS-native offences with no IPC predecessor (snatching, mob lynching, organised crime)
  are stored separately rather than being forced into a mapping.
* The engine reports **which code applies** based on the incident date it extracted, and says
  so explicitly when the date is unknown.

Every provision carries a verification note. The mapping is a working reference, not an
official concordance — there isn't one.

---

## Honesty guarantees

These are enforced by structure, not by good intentions:

* **No invented facts.** The FIR builder reads only from extracted entities, each of which
  carries the exact span of the complaint it came from. Missing fields render as
  *"Not provided"* and stay editable. There is no generative step that could hallucinate a
  witness, a time, or an accused.
* **Failed translation is visible.** If no provider loads, `translate()` returns the
  **original** text with `translated: false` and an error. It never passes untranslated text
  off as a translation.
* **Whisper hallucination filter.** Whisper emits fluent sentences on silence ("Thank you for
  watching"). Segments with high no-speech probability or poor average log-probability are
  **rejected with an honest error** rather than forwarded into a police document.
* **"Potentially relevant", never "confirmed".** Every provision is labelled as a suggestion
  requiring officer verification, in the API, the UI, and the PDF footer of every page.
* **Lost property is not a crime.** A complaint that describes mislaid property returns a
  *lost-property acknowledgement* with "no cognizable offence disclosed", instead of
  manufacturing a theft section.
* **Follow-up questions, not auto-fill.** When details are missing the system lists what the
  officer should ask rather than guessing.

---

## Architecture

```
nyayavoice/
├── backend/
│   ├── app.py                  FastAPI: all endpoints + serves the frontend
│   ├── config.py               languages, regions, blend weights, thresholds
│   ├── database.py             SQLite schema and CRUD
│   ├── services/
│   │   ├── asr.py              Whisper (faster-whisper / openai-whisper) + quality gating
│   │   ├── translation.py      Google / IndicTrans2 / NLLB providers, section-number masking
│   │   ├── nlp_engine.py       entity extraction, date resolution, summarisation
│   │   ├── legal_engine.py     the three-signal provision finder
│   │   ├── fir_builder.py      FIR assembly, English + regional copies
│   │   └── pdf_export.py       fpdf2 + HarfBuzz shaping
│   ├── data/
│   │   ├── legal_kb.json          generated - 344 provisions
│   │   ├── crime_rules.json       25 crime categories, explainable rules
│   │   ├── ipc_bns_map.json       117 curated IPC→BNS mappings
│   │   ├── extra_provisions.json  IT Act, MV Act, POCSO, DV Act, BNS-native
│   │   ├── supplementary_ipc.json 6 IPC sections absent from the dataset
│   │   └── fonts/                 22 Noto TTFs for 11 Indian scripts
│   └── ml/
│       ├── build_kb.py         dataset → legal_kb.json
│       ├── train.py            classifier + retrieval index
│       └── artifacts/          clf_pipeline.joblib, retrieval_index.joblib, metrics.json
├── frontend/
│   ├── index.html              the provided UI, wired to the live API
│   ├── styles.css              the original design system, unchanged + additions
│   └── app.js                  speech capture, analysis, FIR editing, dashboard
├── scripts/
│   ├── fetch_fonts.py          downloads the Noto Indic fonts
│   ├── selftest.py             component-by-component diagnostic
│   └── demo.py                 command-line walkthrough
├── requirements.txt
└── run.sh
```

---

## Speech: two paths, one result

1. **Browser Web Speech API** — instant, gives **live captions while the person is still
   speaking**, needs nothing installed. Chrome and Edge support `te-IN`, `hi-IN`, `ta-IN`,
   `kn-IN`, `ml-IN`, `mr-IN`, `bn-IN`. This is what makes a classroom demo work on any laptop.
2. **MediaRecorder → `POST /api/transcribe` → Whisper** — used when the browser has no speech
   support, when the user chose *auto-detect* (the Web Speech API must be told a locale up
   front, Whisper does not), or when path 1 returns nothing usable.

Both end at the same editable transcript box, which the person confirms before anything is
analysed.

---

## API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/transcribe` | audio → text (multipart; `language` optional for auto-detect) |
| POST | `/api/detect-language` | script-based detection, Hindi/Marathi disambiguated |
| POST | `/api/translate` | any supported pair, section numbers preserved |
| POST | `/api/analyze` | **the whole understanding pipeline in one call** |
| POST | `/api/find-sections` | provisions from English text |
| GET | `/api/provisions/{code}` | full statute detail, e.g. `IPC:379`, `X:BNS304` |
| POST | `/api/generate-fir` | English + regional FIR drafts |
| POST | `/api/generate-pdf` | bilingual PDF + original-transcript annexure |
| GET/POST/PUT/DELETE | `/api/complaints[/{id}]` | CRUD |
| GET | `/api/health` | per-component status, used by the UI's status pills |
| GET | `/api/config` | languages and regions, so the UI is never hard-coded |

Interactive docs at `/docs`.

---

## Languages and regions

13 languages configured: English, Telugu, Hindi, Tamil, Kannada, Malayalam, Marathi, Bengali,
Gujarati, Punjabi, Odia, Urdu, Assamese. 22 regions map to their police working language.

**Adding a language is one entry in `backend/config.py`** — no other file is language-specific.
Add the Noto font for its script to `scripts/fetch_fonts.py` if the script is new.

---

## Database

SQLite by default (`backend/nyayavoice.db`). Tables: `complaints`, `extracted_entities`,
`legal_provisions`, `fir_drafts`, `audit_log`. Entity and FIR rows carry an `edited_by_user`
flag, so AI-generated text and human-corrected text stay distinguishable in the record.

For PostgreSQL: change `INTEGER PRIMARY KEY AUTOINCREMENT` to `SERIAL PRIMARY KEY` and the
`TEXT` timestamp columns to `TIMESTAMPTZ`.

---

## Known limitations

* **Model accuracy is low in absolute terms** (top-3 38.0%) for the domain-mismatch reason
  explained above. It is deliberately weighted at 18%.
* **Location extraction can pick the wrong place** when a complaint mentions several — it may
  capture the hospital rather than the scene. The field is editable and shows the span it came
  from.
* **BNS mapping covers 117 of 326 sections.** The rest are flagged rather than guessed.
* **Translation quality is a heuristic**, based on length and content consistency. It is not a
  measure of legal accuracy, and the label says so.
* **No authentication.** This is a prototype; a real deployment needs officer login, audit
  trails tied to identity, and CORS locked down.
* **Relative dates are resolved against the reporting date** and marked for confirmation —
  "yesterday" becomes a real date because the BNS/IPC decision depends on it, but the
  derivation is always shown.

---

## Disclaimer

> This application generates an AI-assisted complaint/FIR draft and identifies potentially
> relevant legal provisions for informational and administrative assistance. The generated
> content must be reviewed and verified by an authorized police officer or qualified legal
> professional before official use.

Statutory text is reproduced from the supplied academic dataset and, for the supplementary
entries, summarised from the bare acts. Always verify against the official text at
[indiacode.nic.in](https://www.indiacode.nic.in) before any official use.

Built as an academic prototype. Not an official government portal.
