"""
SQLite persistent storage and checkpointing for the Persianization pipeline.
Provides crash-resilience, attempt auditing, response caching with strict invalidation,
atomic state updates, and tracking of dual quality judges.
"""
import os
import json
import sqlite3
import threading
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timezone


class PersianizationStorage:
    """Thread-safe SQLite storage for Persianization records and audit trails."""
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, timeout=60.0)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL;")
            self._local.conn.execute("PRAGMA synchronous=NORMAL;")
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY,
                input_order_idx INTEGER,
                request_id TEXT,
                raw_text TEXT NOT NULL,
                raw_context TEXT,
                original_language TEXT,
                origin TEXT NOT NULL,
                translation_status TEXT NOT NULL,
                quality_status TEXT NOT NULL,
                offense_label TEXT,
                annotation_status TEXT NOT NULL DEFAULT 'not_annotated',
                final_persian_text TEXT,
                final_persian_context TEXT,
                selected_model TEXT,
                evaluator_1_model TEXT,
                quality_scores_json TEXT,
                quality_flags_json TEXT,
                reason TEXT,
                evaluator_2_model TEXT,
                quality_scores_2_json TEXT,
                quality_flags_2_json TEXT,
                second_judge_reason TEXT,
                second_judge_sampling_type TEXT,
                disagreement_flag INTEGER DEFAULT 0,
                source TEXT,
                source_label TEXT,
                parent_id TEXT,
                group_id TEXT,
                split TEXT,
                metadata_json TEXT,
                human_decision TEXT,
                human_edited_text TEXT,
                human_notes TEXT,
                reviewer_name TEXT,
                fingerprint TEXT,
                updated_at_utc TEXT NOT NULL
            );
            """)

            # Non-destructive schema migration for existing databases
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(records);")
            cols = {row["name"] for row in cursor.fetchall()}
            if "fingerprint" not in cols:
                conn.execute("ALTER TABLE records ADD COLUMN fingerprint TEXT;")

            conn.execute("""
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT NOT NULL,
                request_id TEXT,
                step TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                latency_sec REAL,
                raw_completion TEXT,
                parsed_json TEXT,
                status TEXT,
                error_message TEXT,
                created_at_utc TEXT NOT NULL
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                cache_key TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS run_meta (
                run_id TEXT PRIMARY KEY,
                config_json TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                total_records INTEGER,
                total_calls INTEGER,
                total_tokens INTEGER
            );
            """)

    def get_completed_ids(self) -> Set[str]:
        """Returns set of record IDs that are completed and resolved."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM records 
            WHERE quality_status IN ('accepted', 'not_evaluated') 
               OR translation_status IN ('not_required');
        """)
        return {row["id"] for row in cursor.fetchall()}

    def get_all_saved_ids(self) -> Set[str]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM records;")
        return {row["id"] for row in cursor.fetchall()}

    def get_completed_records_map(self) -> Dict[str, Dict[str, Any]]:
        """Returns map of record_id -> metadata for intelligent resume verification."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, raw_text, raw_context, fingerprint, human_decision, input_order_idx FROM records;")
        return {
            row["id"]: {
                "fingerprint": row["fingerprint"],
                "raw_text": row["raw_text"],
                "raw_context": row["raw_context"],
                "human_decision": row["human_decision"],
                "input_order_idx": row["input_order_idx"]
            }
            for row in cursor.fetchall()
        }

    def save_record(self, record_data: Dict[str, Any]) -> None:
        """Upserts a record into the database checkpoint."""
        conn = self._get_connection()
        now = datetime.now(timezone.utc).isoformat()

        scores_1 = record_data.get("quality_scores")
        scores_1_json = json.dumps(scores_1, ensure_ascii=False) if scores_1 else None

        flags_1 = record_data.get("quality_flags")
        flags_1_json = json.dumps(flags_1, ensure_ascii=False) if flags_1 else None

        scores_2 = record_data.get("quality_scores_2")
        scores_2_json = json.dumps(scores_2, ensure_ascii=False) if scores_2 else None

        flags_2 = record_data.get("quality_flags_2")
        flags_2_json = json.dumps(flags_2, ensure_ascii=False) if flags_2 else None

        meta = record_data.get("metadata")
        meta_json = json.dumps(meta, ensure_ascii=False) if meta else None

        src_lbl = record_data.get("source_label")
        src_lbl_str = json.dumps(src_lbl, ensure_ascii=False) if isinstance(src_lbl, (dict, list)) else (str(src_lbl) if src_lbl is not None else None)

        with conn:
            conn.execute("""
            INSERT INTO records (
                id, input_order_idx, request_id, raw_text, raw_context, original_language, origin,
                translation_status, quality_status, offense_label, annotation_status,
                final_persian_text, final_persian_context, selected_model,
                evaluator_1_model, quality_scores_json, quality_flags_json, reason,
                evaluator_2_model, quality_scores_2_json, quality_flags_2_json, second_judge_reason,
                second_judge_sampling_type, disagreement_flag,
                source, source_label, parent_id, group_id, split,
                metadata_json, human_decision, human_edited_text, human_notes, reviewer_name,
                fingerprint, updated_at_utc
            ) VALUES (
                :id, :input_order_idx, :request_id, :raw_text, :raw_context, :original_language, :origin,
                :translation_status, :quality_status, :offense_label, :annotation_status,
                :final_persian_text, :final_persian_context, :selected_model,
                :evaluator_1_model, :quality_scores_json, :quality_flags_json, :reason,
                :evaluator_2_model, :quality_scores_2_json, :quality_flags_2_json, :second_judge_reason,
                :second_judge_sampling_type, :disagreement_flag,
                :source, :source_label, :parent_id, :group_id, :split,
                :metadata_json, :human_decision, :human_edited_text, :human_notes, :reviewer_name,
                :fingerprint, :updated_at_utc
            ) ON CONFLICT(id) DO UPDATE SET
                origin=excluded.origin,
                translation_status=excluded.translation_status,
                quality_status=excluded.quality_status,
                offense_label=excluded.offense_label,
                annotation_status=excluded.annotation_status,
                final_persian_text=excluded.final_persian_text,
                final_persian_context=excluded.final_persian_context,
                selected_model=excluded.selected_model,
                evaluator_1_model=excluded.evaluator_1_model,
                quality_scores_json=excluded.quality_scores_json,
                quality_flags_json=excluded.quality_flags_json,
                reason=excluded.reason,
                evaluator_2_model=excluded.evaluator_2_model,
                quality_scores_2_json=excluded.quality_scores_2_json,
                quality_flags_2_json=excluded.quality_flags_2_json,
                second_judge_reason=excluded.second_judge_reason,
                second_judge_sampling_type=excluded.second_judge_sampling_type,
                disagreement_flag=excluded.disagreement_flag,
                human_decision=COALESCE(excluded.human_decision, records.human_decision),
                human_edited_text=COALESCE(excluded.human_edited_text, records.human_edited_text),
                human_notes=COALESCE(excluded.human_notes, records.human_notes),
                reviewer_name=COALESCE(excluded.reviewer_name, records.reviewer_name),
                fingerprint=excluded.fingerprint,
                updated_at_utc=excluded.updated_at_utc;
            """, {
                "id": record_data["id"],
                "input_order_idx": record_data.get("input_order_idx", 0),
                "request_id": record_data.get("request_id"),
                "raw_text": record_data.get("raw_text") or record_data.get("text"),
                "raw_context": record_data.get("raw_context") or record_data.get("context"),
                "original_language": record_data.get("language") or record_data.get("original_language"),
                "origin": record_data["origin"],
                "translation_status": record_data.get("translation_status", "not_required"),
                "quality_status": record_data.get("quality_status", "not_evaluated"),
                "offense_label": record_data.get("offense_label"),
                "annotation_status": record_data.get("annotation_status", "not_annotated"),
                "final_persian_text": record_data.get("final_persian_text"),
                "final_persian_context": record_data.get("final_persian_context"),
                "selected_model": record_data.get("selected_model"),
                "evaluator_1_model": record_data.get("evaluator_1_model"),
                "quality_scores_json": scores_1_json,
                "quality_flags_json": flags_1_json,
                "reason": record_data.get("reason"),
                "evaluator_2_model": record_data.get("evaluator_2_model"),
                "quality_scores_2_json": scores_2_json,
                "quality_flags_2_json": flags_2_json,
                "second_judge_reason": record_data.get("second_judge_reason"),
                "second_judge_sampling_type": record_data.get("second_judge_sampling_type"),
                "disagreement_flag": 1 if record_data.get("disagreement_flag") else 0,
                "source": record_data.get("source"),
                "source_label": src_lbl_str,
                "parent_id": record_data.get("parent_id"),
                "group_id": record_data.get("group_id"),
                "split": record_data.get("split"),
                "metadata_json": meta_json,
                "human_decision": record_data.get("human_decision"),
                "human_edited_text": record_data.get("human_edited_text"),
                "human_notes": record_data.get("human_notes"),
                "reviewer_name": record_data.get("reviewer_name"),
                "fingerprint": record_data.get("fingerprint"),
                "updated_at_utc": now
            })

    def record_attempt(
        self,
        record_id: str,
        step: str,
        model: str,
        usage: Dict[str, int],
        latency_sec: float,
        raw_completion: str,
        parsed_json: Optional[Dict[str, Any]],
        status: str,
        error_message: Optional[str] = None,
        request_id: Optional[str] = None
    ) -> None:
        """Logs an API model invocation attempt."""
        conn = self._get_connection()
        now = datetime.now(timezone.utc).isoformat()
        with conn:
            conn.execute("""
            INSERT INTO attempts (
                record_id, request_id, step, model, prompt_tokens, completion_tokens, total_tokens,
                latency_sec, raw_completion, parsed_json, status, error_message, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                record_id,
                request_id,
                step,
                model,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                usage.get("total_tokens", 0),
                latency_sec,
                raw_completion,
                json.dumps(parsed_json, ensure_ascii=False) if parsed_json else None,
                status,
                error_message,
                now
            ))

    def get_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT response_json FROM cache WHERE cache_key = ?;", (cache_key,))
        row = cursor.fetchone()
        if row:
            try:
                return json.loads(row["response_json"])
            except Exception:
                return None
        return None

    def set_cache(self, cache_key: str, data: Dict[str, Any]) -> None:
        conn = self._get_connection()
        now = datetime.now(timezone.utc).isoformat()
        with conn:
            conn.execute("""
            INSERT OR REPLACE INTO cache (cache_key, response_json, created_at_utc)
            VALUES (?, ?, ?);
            """, (cache_key, json.dumps(data, ensure_ascii=False), now))

    def fetch_all_records(self) -> List[Dict[str, Any]]:
        """Retrieves all records as dictionaries, ordered by input order."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM records ORDER BY input_order_idx, id;")
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            d["text"] = d.get("final_persian_text") or d.get("raw_text")
            for k in ("quality_scores_json", "quality_flags_json", "quality_scores_2_json", "quality_flags_2_json", "metadata_json"):
                if d.get(k):
                    try:
                        d[k.replace("_json", "")] = json.loads(d[k])
                    except Exception:
                        d[k.replace("_json", "")] = None
            results.append(d)
        return results

    def fetch_record_by_id(self, record_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single record by its ID with JSON fields deserialized."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM records WHERE id = ?;", (record_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["text"] = d.get("final_persian_text") or d.get("raw_text")
        for k in ("quality_scores_json", "quality_flags_json", "quality_scores_2_json", "quality_flags_2_json", "metadata_json"):
            if d.get(k):
                try:
                    d[k.replace("_json", "")] = json.loads(d[k])
                except Exception:
                    d[k.replace("_json", "")] = None
            else:
                d[k.replace("_json", "")] = None
        return d

    def fetch_all_attempts(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM attempts ORDER BY id;")
        return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None
