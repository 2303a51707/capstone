"""
fetch_fonts.py - downloads the Noto fonts the PDF exporter needs for Indic scripts.

Run once after cloning:   python scripts/fetch_fonts.py

Fonts land in backend/data/fonts/ and are licensed under the SIL Open Font License 1.1.
Without them the PDF exporter still works, but any non-Latin script falls back to
boxes, so the exporter refuses to produce a regional-language PDF and says why.
"""
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "backend", "data", "fonts")
BASE = "https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/fonts"

FAMILIES = {
    "NotoSans": "latin (English and transliteration)",
    "NotoSansDevanagari": "Hindi, Marathi",
    "NotoSansTelugu": "Telugu",
    "NotoSansTamil": "Tamil",
    "NotoSansKannada": "Kannada",
    "NotoSansMalayalam": "Malayalam",
    "NotoSansBengali": "Bengali, Assamese",
    "NotoSansGujarati": "Gujarati",
    "NotoSansGurmukhi": "Punjabi",
    "NotoSansOriya": "Odia",
    "NotoSansArabic": "Urdu",
}
STYLES = ("Regular", "Bold")


def fetch(family: str, style: str) -> bool:
    filename = f"{family}-{style}.ttf"
    target = os.path.join(OUT, filename)
    if os.path.exists(target) and os.path.getsize(target) > 10_000:
        print(f"  = {filename} (already present)")
        return True
    url = f"{BASE}/{family}/hinted/ttf/{filename}"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        if len(data) < 10_000:
            raise ValueError("file looks truncated")
        with open(target, "wb") as fh:
            fh.write(data)
        print(f"  + {filename}  ({len(data)//1024} KB)")
        return True
    except Exception as exc:
        print(f"  ! {filename} failed: {exc}")
        return False


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"Downloading Noto fonts into {os.path.realpath(OUT)}\n")
    ok = 0
    total = 0
    for family, languages in FAMILIES.items():
        print(f"{family}  ->  {languages}")
        for style in STYLES:
            total += 1
            ok += 1 if fetch(family, style) else 0
    print(f"\n{ok}/{total} font files available.")
    if ok < total:
        print("Some downloads failed. Re-run when you have a connection, or drop the "
              "TTF files into backend/data/fonts/ manually.")
        sys.exit(1)


if __name__ == "__main__":
    main()
