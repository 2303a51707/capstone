"""
build_kb.py - turns the uploaded IPC dataset into a structured legal knowledge base.

Input : indian_ipc_statute_identification.csv  (case_facts, ipc_section, statute_text)
Output: backend/data/legal_kb.json

For every IPC section present in the dataset this produces:
    section_number, law_name, offence_name, description, elements,
    punishment, keywords, bns_section, mapping_status, n_training_cases

Run:  python backend/ml/build_kb.py --csv /path/to/indian_ipc_statute_identification.csv
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")

PREFIX_RE = re.compile(r"^\s*Section\s+([0-9]+[A-Za-z]*)\s+of the Indian Penal Code\.\s*", re.I)
BODY_STARTERS = re.compile(
    r"^(Whoever|Whenever|When |Whosoever|If any|If a |If the |A person|Any person|Every|In every|"
    r"Nothing |The word|The words|Where |It is |No person|Illustration)", re.I
)
PUNISH_RE = re.compile(
    r"(shall be punished[^.;]*(?:[.;]|$)|shall also be liable to fine|"
    r"shall be liable to fine[^.;]*(?:[.;]|$))", re.I
)

STOPWORDS = set("""a an the of and or to in for with by on at as is are be been being shall may such any
person persons whoever which that this these those who whom whose he she it they them his her its their
other others otherwise both either neither not no nor if when whenever where whereas thereof therein
thereto hereby said same so than then there here from into upon under over out up down off but also
section sections code indian penal punished punishment imprisonment term extend years year description
liable fine rupees one two three four five six seven ten fourteen twenty explanation illustration
provided case cases means mean word words act acts done doing shall_be""".split())


def parse_title_and_body(statute_text: str):
    """'Section 379 of the IPC. Theft. Whoever commits theft...' -> ('Theft', 'Whoever commits ...')"""
    text = re.sub(r"\s+", " ", str(statute_text)).strip()
    rest = PREFIX_RE.sub("", text)
    parts = re.split(r"(?<=\.)\s+", rest)
    title_parts, body_parts, in_title = [], [], True
    for part in parts:
        if in_title:
            candidate = " ".join(title_parts + [part])
            # the marginal title ends once operative language begins, or once it gets long
            if title_parts and (BODY_STARTERS.match(part) or len(candidate) > 220):
                in_title = False
                body_parts.append(part)
            elif not title_parts and BODY_STARTERS.match(part):
                # no title at all in this record
                in_title = False
                body_parts.append(part)
            else:
                title_parts.append(part)
                # a title ending in a full stop and not in 'etc.' closes the title
                if part.rstrip().endswith(".") and not re.search(r"\betc\.$", part.strip(), re.I):
                    in_title = False
        else:
            body_parts.append(part)
    title = " ".join(title_parts).strip().rstrip(".").strip()
    body = " ".join(body_parts).strip()
    if not body:
        body = title
    return title, body


def extract_punishment(body: str) -> str:
    hits = PUNISH_RE.findall(body)
    if not hits:
        return "Refer to the bare act"
    out = " ".join(h.strip() for h in hits[:2])
    out = re.sub(r"\s+", " ", out).strip(" ;.")
    return (out[:300] + "...") if len(out) > 300 else out


def extract_elements(body: str, max_elements: int = 6):
    """Split the operative text into the ingredients an officer must satisfy."""
    txt = re.sub(r"\s+", " ", body)
    txt = re.sub(r"^(Whoever|Whosoever)\s+", "", txt, flags=re.I)
    txt = re.split(r"shall be punished", txt, flags=re.I)[0]
    chunks = re.split(r",\s+(?:or\s+)?|;\s*|\s+and\s+(?=[a-z])", txt)
    elements = []
    for chunk in chunks:
        chunk = chunk.strip(" ,.;:")
        if 12 <= len(chunk) <= 160 and not chunk.lower().startswith("except"):
            chunk = chunk[0].upper() + chunk[1:]
            elements.append(chunk)
        if len(elements) >= max_elements:
            break
    return elements


def keywords_from(title: str, body: str, extra_corpus: str = "", top_n: int = 18):
    text = f"{title} {title} {title} {body} {extra_corpus}".lower()
    words = re.findall(r"[a-z][a-z\-]{3,}", text)
    words = [w for w in words if w not in STOPWORDS]
    common = [w for w, _ in Counter(words).most_common(top_n * 2)]
    bigrams = []
    title_words = [w for w in re.findall(r"[a-z\-]{3,}", title.lower()) if w not in STOPWORDS]
    for i in range(len(title_words) - 1):
        bigrams.append(f"{title_words[i]} {title_words[i+1]}")
    return list(dict.fromkeys(bigrams + common))[:top_n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.environ.get("IPC_CSV", ""), help="path to the IPC dataset CSV")
    ap.add_argument("--out", default=os.path.join(DATA, "legal_kb.json"))
    args = ap.parse_args()

    if not args.csv or not os.path.exists(args.csv):
        sys.exit("CSV not found. Pass --csv /path/to/indian_ipc_statute_identification.csv")

    print(f"Reading {args.csv} ...")
    df = pd.read_csv(args.csv, usecols=["case_facts", "ipc_section", "statute_text"])
    df["ipc_section"] = df["ipc_section"].astype(str).str.strip()
    counts = df["ipc_section"].value_counts().to_dict()
    print(f"  {len(df):,} rows, {len(counts)} distinct sections")

    with open(os.path.join(DATA, "ipc_bns_map.json"), encoding="utf-8") as fh:
        bns_map = json.load(fh)["map"]

    sections = {}
    for section, group in df.groupby("ipc_section"):
        statute_text = group["statute_text"].mode().iloc[0]
        title, body = parse_title_and_body(statute_text)
        mapped = bns_map.get(section)
        sections[section] = {
            "code": f"IPC:{section}",
            "section_number": section,
            "law_name": "Indian Penal Code, 1860 (repealed for offences on or after 1 July 2024)",
            "offence_name": title or f"IPC Section {section}",
            "description": body,
            "elements": extract_elements(body),
            "punishment": extract_punishment(body),
            "keywords": keywords_from(title, body),
            "bns_section": (mapped or {}).get("bns"),
            "bns_offence_name": (mapped or {}).get("title"),
            "mapping_status": (
                "mapped" if mapped and mapped.get("bns")
                else "no_bns_equivalent" if mapped else "unmapped"
            ),
            "n_training_cases": int(counts.get(section, 0)),
            "source": "uploaded dataset: indian_ipc_statute_identification.csv",
        }

    # IPC sections the dataset does not cover, supplied from the bare act
    supp_path = os.path.join(DATA, "supplementary_ipc.json")
    n_supp = 0
    if os.path.exists(supp_path):
        with open(supp_path, encoding="utf-8") as fh:
            supp = json.load(fh)["sections"]
        for section, entry in supp.items():
            if section in sections:
                continue
            mapped = bns_map.get(section)
            body = entry["description"]
            sections[section] = {
                "code": f"IPC:{section}",
                "section_number": section,
                "law_name": "Indian Penal Code, 1860 (repealed for offences on or after 1 July 2024)",
                "offence_name": entry["offence_name"],
                "description": body,
                "elements": extract_elements(body),
                "punishment": entry.get("punishment", "Refer to the bare act"),
                "keywords": entry.get("keywords", []) + keywords_from(entry["offence_name"], body, top_n=10),
                "bns_section": (mapped or {}).get("bns"),
                "bns_offence_name": (mapped or {}).get("title"),
                "mapping_status": (
                    "mapped" if mapped and mapped.get("bns")
                    else "no_bns_equivalent" if mapped else "unmapped"
                ),
                "n_training_cases": 0,
                "source": "curated from the bare act (not present in the uploaded dataset)",
            }
            n_supp += 1

    # non-IPC provisions (IT Act, MV Act, POCSO, BNS-native offences, procedural entries)
    with open(os.path.join(DATA, "extra_provisions.json"), encoding="utf-8") as fh:
        extras = json.load(fh)["provisions"]
    extra_out = {}
    for p in extras:
        extra_out[p["code"]] = {
            "code": f"X:{p['code']}",
            "section_number": p["section_number"],
            "law_name": p["law_name"],
            "offence_name": p["offence_name"],
            "description": p["description"],
            "elements": extract_elements(p["description"]),
            "punishment": p.get("punishment", "Refer to the bare act"),
            "keywords": p.get("keywords", []),
            "bns_section": p["section_number"] if p.get("flag") == "BNS_NATIVE" else None,
            "bns_offence_name": p["offence_name"] if p.get("flag") == "BNS_NATIVE" else None,
            "mapping_status": "current_law",
            "flag": p.get("flag"),
            "n_training_cases": 0,
            "source": "curated (special and local laws / BNS-native offences)",
        }

    kb = {
        "_meta": {
            "built_from": os.path.basename(args.csv),
            "n_ipc_sections": len(sections),
            "n_supplementary_ipc": n_supp,
            "n_extra_provisions": len(extra_out),
            "n_training_rows": int(len(df)),
            "disclaimer": "Section text is reproduced from the uploaded academic dataset. "
                          "The BNS mapping is a curated working reference and must be verified "
                          "against the bare act at indiacode.nic.in before official use.",
        },
        "ipc": sections,
        "extra": extra_out,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(kb, fh, ensure_ascii=False, indent=1)

    mapped_n = sum(1 for s in sections.values() if s["mapping_status"] == "mapped")
    print(f"Wrote {args.out}")
    print(f"  IPC sections      : {len(sections)}")
    print(f"  BNS-mapped        : {mapped_n} ({mapped_n/len(sections)*100:.0f}%)")
    print(f"  Extra provisions  : {len(extra_out)}")


if __name__ == "__main__":
    main()
