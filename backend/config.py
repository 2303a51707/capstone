"""Central configuration for NyayaVoice."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ARTIFACT_DIR = os.path.join(BASE_DIR, "ml", "artifacts")
FONT_DIR = os.path.join(DATA_DIR, "fonts")
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")
DB_PATH = os.environ.get("NYAYAVOICE_DB", os.path.join(BASE_DIR, "nyayavoice.db"))

# ----------------------------------------------------------------- ASR
# tiny | base | small | medium | large-v3 . 'small' is the sensible default on a laptop.
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8")

# ----------------------------------------------------------- Translation
# Provider order is tried top to bottom; the first one that loads wins.
#   google  - deep-translator, needs internet, no key, good Indian-language quality
#   indictrans2 - AI4Bharat IndicTrans2 via transformers, runs offline after first download
#   nllb    - facebook/nllb-200-distilled-600M via transformers, offline after download
TRANSLATION_PROVIDERS = os.environ.get(
    "TRANSLATION_PROVIDERS", "google,nllb"
).split(",")

# --------------------------------------------------------- Legal engine
# Blend weights for the three signals. They must sum to 1.0.
WEIGHT_RULES = float(os.environ.get("WEIGHT_RULES", 0.50))
WEIGHT_RETRIEVAL = float(os.environ.get("WEIGHT_RETRIEVAL", 0.32))
WEIGHT_MODEL = float(os.environ.get("WEIGHT_MODEL", 0.18))

MAX_PROVISIONS = int(os.environ.get("MAX_PROVISIONS", 6))
MIN_PROVISION_SCORE = float(os.environ.get("MIN_PROVISION_SCORE", 0.18))
# A provision that no rule proposed - surfaced only by similarity or by the model -
# has to clear a higher bar before it is shown, otherwise weak lexical overlap
# ("stolen property" in an unrelated section) clutters the result.
MIN_UNRULED_SCORE = float(os.environ.get("MIN_UNRULED_SCORE", 0.35))

# What counts as a full-strength signal, used to put retrieval and the model on
# the same 0-1 scale as the rule score. These are measured ceilings, not guesses:
# TF-IDF cosine between a 20-word complaint and a statute description tops out
# around 0.26 in practice, so a higher value here silently caps the retrieval
# signal at a fraction of its configured weight and understates every result.
RETRIEVAL_FULL_MATCH = float(os.environ.get("RETRIEVAL_FULL_MATCH", 0.22))
MODEL_FULL_MATCH = float(os.environ.get("MODEL_FULL_MATCH", 0.22))

# The date that decides whether the BNS or the IPC applies to an offence.
BNS_CUTOVER = "2024-07-01"

# ------------------------------------------------------------ Languages
LANGUAGES = {
    "en": {"name": "English",   "native": "English",   "script": "latin",       "whisper": "en", "google": "en",  "speech": "en-IN", "flores": "eng_Latn"},
    "te": {"name": "Telugu",    "native": "తెలుగు",     "script": "telugu",      "whisper": "te", "google": "te",  "speech": "te-IN", "flores": "tel_Telu"},
    "hi": {"name": "Hindi",     "native": "हिन्दी",      "script": "devanagari",  "whisper": "hi", "google": "hi",  "speech": "hi-IN", "flores": "hin_Deva"},
    "ta": {"name": "Tamil",     "native": "தமிழ்",      "script": "tamil",       "whisper": "ta", "google": "ta",  "speech": "ta-IN", "flores": "tam_Taml"},
    "kn": {"name": "Kannada",   "native": "ಕನ್ನಡ",      "script": "kannada",     "whisper": "kn", "google": "kn",  "speech": "kn-IN", "flores": "kan_Knda"},
    "ml": {"name": "Malayalam", "native": "മലയാളം",    "script": "malayalam",   "whisper": "ml", "google": "ml",  "speech": "ml-IN", "flores": "mal_Mlym"},
    "mr": {"name": "Marathi",   "native": "मराठी",      "script": "devanagari",  "whisper": "mr", "google": "mr",  "speech": "mr-IN", "flores": "mar_Deva"},
    "bn": {"name": "Bengali",   "native": "বাংলা",       "script": "bengali",     "whisper": "bn", "google": "bn",  "speech": "bn-IN", "flores": "ben_Beng"},
    # Adding a language is a single entry here - nothing else in the codebase is language-specific.
    "gu": {"name": "Gujarati",  "native": "ગુજરાતી",     "script": "gujarati",    "whisper": "gu", "google": "gu",  "speech": "gu-IN", "flores": "guj_Gujr"},
    "pa": {"name": "Punjabi",   "native": "ਪੰਜਾਬੀ",      "script": "gurmukhi",    "whisper": "pa", "google": "pa",  "speech": "pa-IN", "flores": "pan_Guru"},
    "or": {"name": "Odia",      "native": "ଓଡ଼ିଆ",       "script": "odia",        "whisper": "or", "google": "or",  "speech": "or-IN", "flores": "ory_Orya"},
    "ur": {"name": "Urdu",      "native": "اردو",       "script": "arabic",      "whisper": "ur", "google": "ur",  "speech": "ur-IN", "flores": "urd_Arab"},
    "as": {"name": "Assamese",  "native": "অসমীয়া",     "script": "bengali",     "whisper": "as", "google": "as",  "speech": "as-IN", "flores": "asm_Beng"},
}

# Police-station region -> official working language of that state's police.
# Configurable, not hard-coded into the pipeline.
REGIONS = {
    "Telangana":       {"lang": "te", "capital": "Hyderabad"},
    "Andhra Pradesh":  {"lang": "te", "capital": "Amaravati"},
    "Kerala":          {"lang": "ml", "capital": "Thiruvananthapuram"},
    "Tamil Nadu":      {"lang": "ta", "capital": "Chennai"},
    "Karnataka":       {"lang": "kn", "capital": "Bengaluru"},
    "Maharashtra":     {"lang": "mr", "capital": "Mumbai"},
    "West Bengal":     {"lang": "bn", "capital": "Kolkata"},
    "Gujarat":         {"lang": "gu", "capital": "Gandhinagar"},
    "Punjab":          {"lang": "pa", "capital": "Chandigarh"},
    "Odisha":          {"lang": "or", "capital": "Bhubaneswar"},
    "Assam":           {"lang": "as", "capital": "Dispur"},
    "Delhi":           {"lang": "hi", "capital": "New Delhi"},
    "Uttar Pradesh":   {"lang": "hi", "capital": "Lucknow"},
    "Bihar":           {"lang": "hi", "capital": "Patna"},
    "Madhya Pradesh":  {"lang": "hi", "capital": "Bhopal"},
    "Rajasthan":       {"lang": "hi", "capital": "Jaipur"},
    "Haryana":         {"lang": "hi", "capital": "Chandigarh"},
    "Jharkhand":       {"lang": "hi", "capital": "Ranchi"},
    "Chhattisgarh":    {"lang": "hi", "capital": "Raipur"},
    "Uttarakhand":     {"lang": "hi", "capital": "Dehradun"},
    "Himachal Pradesh": {"lang": "hi", "capital": "Shimla"},
    "Goa":             {"lang": "mr", "capital": "Panaji"},
}

DISCLAIMER = (
    "This application generates an AI-assisted complaint/FIR draft and identifies "
    "potentially relevant legal provisions for informational and administrative "
    "assistance. The generated content must be reviewed and verified by an authorized "
    "police officer or qualified legal professional before official use."
)


_REGION_LOOKUP = {key.strip().lower(): value for key, value in REGIONS.items()}


def region_language(region: str) -> str:
    # Matched case-insensitively: an exact lookup silently returned "en" for
    # "telangana", which skipped the regional copy and reported it as intended.
    return _REGION_LOOKUP.get((region or "").strip().lower(), {}).get("lang", "en")


def lang_name(code: str) -> str:
    return LANGUAGES.get(code, {}).get("name", code)