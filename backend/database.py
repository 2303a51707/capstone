"""
database.py - SQLite persistence.

Schema follows section 18 of the project specification: complaints, extracted_entities,
legal_provisions and fir_drafts. SQLite for development; the same SQL runs on PostgreSQL
with the two noted type changes in the README.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import Dict, List, Optional

from . import config

_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS complaints (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_number    TEXT UNIQUE NOT NULL,
    original_language   TEXT NOT NULL,
    police_region       TEXT NOT NULL,
    regional_language   TEXT NOT NULL,
    police_station      TEXT,
    original_transcript TEXT NOT NULL,
    english_translation TEXT NOT NULL,
    crime_type          TEXT,
    crime_confidence    INTEGER,
    input_mode          TEXT DEFAULT 'voice',
    status              TEXT DEFAULT 'draft',
    incident_date_iso   TEXT,
    summary             TEXT,
    analysis_json       TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extracted_entities (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
    entity_type  TEXT NOT NULL,
    entity_value TEXT,
    evidence     TEXT,
    source       TEXT,
    confidence   TEXT,
    edited_by_user INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS legal_provisions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id   INTEGER REFERENCES complaints(id) ON DELETE CASCADE,
    code           TEXT NOT NULL,
    law_name       TEXT,
    section_number TEXT,
    offence_name   TEXT,
    description    TEXT,
    punishment     TEXT,
    keywords       TEXT,
    relevance      TEXT,
    confidence     INTEGER,
    matching_reason TEXT,
    signals_json   TEXT,
    officer_status TEXT DEFAULT 'unverified'
);

CREATE TABLE IF NOT EXISTS fir_drafts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id      INTEGER NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
    english_fir       TEXT NOT NULL,
    regional_fir      TEXT,
    regional_language TEXT,
    field_labels      TEXT,
    regional_labels   TEXT,
    version           INTEGER DEFAULT 1,
    edited_by_user    INTEGER DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER REFERENCES complaints(id) ON DELETE CASCADE,
    event        TEXT NOT NULL,
    detail       TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_complaints_created ON complaints(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_entities_complaint ON extracted_entities(complaint_id);
CREATE INDEX IF NOT EXISTS idx_provisions_complaint ON legal_provisions(complaint_id);
CREATE INDEX IF NOT EXISTS idx_drafts_complaint ON fir_drafts(complaint_id);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init():
    with _LOCK, connect() as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(conn, complaint_id: Optional[int], event: str, detail: str = ""):
    conn.execute(
        "INSERT INTO audit_log (complaint_id, event, detail, created_at) VALUES (?,?,?,?)",
        (complaint_id, event, detail, _now()),
    )


# ---------------------------------------------------------------- complaints
def next_reference() -> str:
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM complaints").fetchone()
    return f"NV-{datetime.now().year}-{row['n'] + 1:04d}"


def save_complaint(payload: Dict) -> Dict:
    """Persist a complaint with its entities, provisions and FIR drafts in one transaction."""
    reference = payload.get("reference_number") or next_reference()
    now = _now()
    with _LOCK, connect() as conn:
        cursor = conn.execute(
            """INSERT INTO complaints
               (reference_number, original_language, police_region, regional_language,
                police_station, original_transcript, english_translation, crime_type,
                crime_confidence, input_mode, status, incident_date_iso, summary,
                analysis_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (reference, payload.get("original_language", "en"),
             payload.get("police_region", ""), payload.get("regional_language", "en"),
             payload.get("police_station"), payload.get("original_transcript", ""),
             payload.get("english_translation", ""), payload.get("crime_type"),
             payload.get("crime_confidence"), payload.get("input_mode", "voice"),
             payload.get("status", "draft"), payload.get("incident_date_iso"),
             payload.get("summary"),
             json.dumps(payload.get("analysis", {}), ensure_ascii=False), now, now),
        )
        complaint_id = cursor.lastrowid

        for key, field in (payload.get("entities") or {}).items():
            if not field:
                continue
            value = field.get("value") if isinstance(field, dict) else field
            conn.execute(
                """INSERT INTO extracted_entities
                   (complaint_id, entity_type, entity_value, evidence, source, confidence)
                   VALUES (?,?,?,?,?,?)""",
                (complaint_id, key, str(value),
                 (field or {}).get("evidence") if isinstance(field, dict) else None,
                 (field or {}).get("source") if isinstance(field, dict) else "user",
                 (field or {}).get("confidence") if isinstance(field, dict) else None),
            )

        for provision in payload.get("provisions") or []:
            conn.execute(
                """INSERT INTO legal_provisions
                   (complaint_id, code, law_name, section_number, offence_name, description,
                    punishment, keywords, relevance, confidence, matching_reason, signals_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (complaint_id, provision.get("code"), provision.get("law_name"),
                 provision.get("section_label"), provision.get("offence_name"),
                 provision.get("description"), provision.get("punishment"),
                 json.dumps(provision.get("elements", []), ensure_ascii=False),
                 provision.get("relevance"), provision.get("confidence"),
                 provision.get("matching_reason"),
                 json.dumps(provision.get("signals", {}), ensure_ascii=False)),
            )

        if payload.get("english_fir"):
            conn.execute(
                """INSERT INTO fir_drafts
                   (complaint_id, english_fir, regional_fir, regional_language,
                    field_labels, regional_labels, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (complaint_id,
                 json.dumps(payload["english_fir"], ensure_ascii=False),
                 json.dumps(payload.get("regional_fir"), ensure_ascii=False),
                 payload.get("regional_language", "en"),
                 json.dumps(payload.get("field_labels", {}), ensure_ascii=False),
                 json.dumps(payload.get("regional_labels", {}), ensure_ascii=False),
                 now, now),
            )

        log(conn, complaint_id, "complaint_saved",
            f"language={payload.get('original_language')} region={payload.get('police_region')}")
        conn.commit()

    return get_complaint(complaint_id)


def list_complaints(query: str = "", limit: int = 100) -> List[Dict]:
    sql = """SELECT c.*,
                    (SELECT COUNT(*) FROM fir_drafts d WHERE d.complaint_id = c.id) AS n_drafts,
                    (SELECT COUNT(*) FROM legal_provisions p WHERE p.complaint_id = c.id) AS n_provisions
             FROM complaints c"""
    params: List = []
    if query:
        sql += """ WHERE c.reference_number LIKE ? OR c.crime_type LIKE ?
                      OR c.english_translation LIKE ? OR c.police_region LIKE ?"""
        like = f"%{query}%"
        params = [like, like, like, like]
    sql += " ORDER BY c.created_at DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_complaint(complaint_id: int) -> Optional[Dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,)).fetchone()
        if not row:
            return None
        complaint = dict(row)
        complaint["analysis"] = json.loads(complaint.pop("analysis_json") or "{}")
        complaint["entities"] = [dict(r) for r in conn.execute(
            "SELECT * FROM extracted_entities WHERE complaint_id = ?", (complaint_id,))]
        complaint["provisions"] = [dict(r) for r in conn.execute(
            "SELECT * FROM legal_provisions WHERE complaint_id = ? ORDER BY confidence DESC",
            (complaint_id,))]
        draft = conn.execute(
            "SELECT * FROM fir_drafts WHERE complaint_id = ? ORDER BY version DESC LIMIT 1",
            (complaint_id,)).fetchone()
        if draft:
            draft = dict(draft)
            for key in ("english_fir", "regional_fir", "field_labels", "regional_labels"):
                draft[key] = json.loads(draft[key]) if draft.get(key) else None
            complaint["draft"] = draft
        else:
            complaint["draft"] = None
        complaint["history"] = [dict(r) for r in conn.execute(
            "SELECT * FROM audit_log WHERE complaint_id = ? ORDER BY id", (complaint_id,))]
    return complaint


def update_complaint(complaint_id: int, changes: Dict) -> Optional[Dict]:
    """Apply officer edits. Edited fields are flagged so AI text and human text stay distinct."""
    now = _now()
    with _LOCK, connect() as conn:
        exists = conn.execute("SELECT id FROM complaints WHERE id = ?", (complaint_id,)).fetchone()
        if not exists:
            return None

        allowed = {"crime_type", "status", "police_station", "police_region",
                   "english_translation", "summary", "incident_date_iso"}
        fields = {k: v for k, v in changes.items() if k in allowed}
        if fields:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE complaints SET {assignments}, updated_at = ? WHERE id = ?",
                         [*fields.values(), now, complaint_id])

        if "english_fir" in changes and changes["english_fir"]:
            row = conn.execute(
                "SELECT id, version FROM fir_drafts WHERE complaint_id = ? "
                "ORDER BY version DESC LIMIT 1", (complaint_id,)).fetchone()
            payload = json.dumps(changes["english_fir"], ensure_ascii=False)
            regional = json.dumps(changes.get("regional_fir"), ensure_ascii=False) \
                if changes.get("regional_fir") is not None else None
            if row:
                conn.execute(
                    "UPDATE fir_drafts SET english_fir = ?, "
                    "regional_fir = COALESCE(?, regional_fir), edited_by_user = 1, "
                    "updated_at = ? WHERE id = ?",
                    (payload, regional, now, row["id"]))
            else:
                conn.execute(
                    "INSERT INTO fir_drafts (complaint_id, english_fir, regional_fir, "
                    "regional_language, edited_by_user, created_at, updated_at) "
                    "VALUES (?,?,?,?,1,?,?)",
                    (complaint_id, payload, regional, changes.get("regional_language", "en"),
                     now, now))

        if "entities" in changes and isinstance(changes["entities"], dict):
            for key, value in changes["entities"].items():
                existing = conn.execute(
                    "SELECT id FROM extracted_entities WHERE complaint_id = ? AND entity_type = ?",
                    (complaint_id, key)).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE extracted_entities SET entity_value = ?, source = 'user', "
                        "edited_by_user = 1 WHERE id = ?", (str(value), existing["id"]))
                else:
                    conn.execute(
                        "INSERT INTO extracted_entities (complaint_id, entity_type, entity_value, "
                        "source, edited_by_user) VALUES (?,?,?,'user',1)",
                        (complaint_id, key, str(value)))

        log(conn, complaint_id, "complaint_updated", ", ".join(changes.keys()))
        conn.commit()
    return get_complaint(complaint_id)


def delete_complaint(complaint_id: int) -> bool:
    with _LOCK, connect() as conn:
        cursor = conn.execute("DELETE FROM complaints WHERE id = ?", (complaint_id,))
        conn.commit()
        return cursor.rowcount > 0


def stats() -> Dict:
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM complaints").fetchone()["n"]
        drafts = conn.execute(
            "SELECT COUNT(*) n FROM complaints WHERE status = 'draft'").fetchone()["n"]
        reviewed = conn.execute(
            "SELECT COUNT(*) n FROM complaints WHERE status = 'reviewed'").fetchone()["n"]
        languages = conn.execute(
            "SELECT COUNT(DISTINCT original_language) n FROM complaints").fetchone()["n"]
    return {"total_complaints": total, "draft_firs": drafts,
            "completed_reviews": reviewed, "languages_used": languages}
