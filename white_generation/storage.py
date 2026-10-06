"""
SQLite state storage and checkpointing for Project B (White Generation).
Maintains full traceability from seed to generated variant, quality audit, and 4-judge votes.
"""
import os
import json
import sqlite3
import threading
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timezone


class WhiteGenerationStorage:
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
            CREATE TABLE IF NOT EXISTS candidates (
                id TEXT PRIMARY KEY,
                seed_id TEXT NOT NULL,
                parent_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                split TEXT,
                seed_text TEXT NOT NULL,
                seed_source_label TEXT,
                recipe TEXT NOT NULL,
                candidate_text TEXT,
                candidate_context TEXT,
                origin TEXT NOT NULL DEFAULT 'generated_white',
                generator_status TEXT NOT NULL,
                persian_quality_score REAL,
                quality_status TEXT NOT NULL,
                judge_votes_json TEXT,
                consensus_status TEXT,
                final_label INTEGER,
                final_status TEXT NOT NULL,
                flags_json TEXT,
                reason TEXT,
                generator_model TEXT,
                human_decision TEXT,
                human_edited_text TEXT,
                human_notes TEXT,
                reviewer_name TEXT,
                updated_at_utc TEXT NOT NULL
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT NOT NULL,
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

    def get_completed_candidate_keys(self) -> Set[str]:
        """Returns set of (seed_id, recipe) that have already been evaluated."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM candidates WHERE final_status != 'unresolved';")
        return {row["id"] for row in cursor.fetchall()}

    def save_candidate(self, cand_data: Dict[str, Any]) -> None:
        conn = self._get_connection()
        now = datetime.now(timezone.utc).isoformat()

        votes_json = json.dumps(cand_data.get("judge_votes"), ensure_ascii=False) if cand_data.get("judge_votes") else None
        flags_json = json.dumps(cand_data.get("flags"), ensure_ascii=False) if cand_data.get("flags") else None
        seed_label = cand_data.get("seed_source_label")
        seed_lbl_str = json.dumps(seed_label, ensure_ascii=False) if isinstance(seed_label, (dict, list)) else (str(seed_label) if seed_label is not None else None)

        with conn:
            conn.execute("""
            INSERT INTO candidates (
                id, seed_id, parent_id, group_id, split,
                seed_text, seed_source_label, recipe,
                candidate_text, candidate_context, origin,
                generator_status, persian_quality_score, quality_status,
                judge_votes_json, consensus_status, final_label,
                final_status, flags_json, reason, generator_model,
                human_decision, human_edited_text, human_notes, reviewer_name,
                updated_at_utc
            ) VALUES (
                :id, :seed_id, :parent_id, :group_id, :split,
                :seed_text, :seed_source_label, :recipe,
                :candidate_text, :candidate_context, :origin,
                :generator_status, :persian_quality_score, :quality_status,
                :judge_votes_json, :consensus_status, :final_label,
                :final_status, :flags_json, :reason, :generator_model,
                :human_decision, :human_edited_text, :human_notes, :reviewer_name,
                :updated_at_utc
            ) ON CONFLICT(id) DO UPDATE SET
                candidate_text=excluded.candidate_text,
                generator_status=excluded.generator_status,
                persian_quality_score=excluded.persian_quality_score,
                quality_status=excluded.quality_status,
                judge_votes_json=excluded.judge_votes_json,
                consensus_status=excluded.consensus_status,
                final_label=excluded.final_label,
                final_status=excluded.final_status,
                flags_json=excluded.flags_json,
                reason=excluded.reason,
                human_decision=excluded.human_decision,
                human_edited_text=excluded.human_edited_text,
                human_notes=excluded.human_notes,
                reviewer_name=excluded.reviewer_name,
                updated_at_utc=excluded.updated_at_utc;
            """, {
                "id": cand_data["id"],
                "seed_id": cand_data["seed_id"],
                "parent_id": cand_data["parent_id"],
                "group_id": cand_data["group_id"],
                "split": cand_data.get("split", "unassigned"),
                "seed_text": cand_data["seed_text"],
                "seed_source_label": seed_lbl_str,
                "recipe": cand_data["recipe"],
                "candidate_text": cand_data.get("candidate_text"),
                "candidate_context": cand_data.get("candidate_context"),
                "origin": "generated_white",
                "generator_status": cand_data.get("generator_status", "generated"),
                "persian_quality_score": cand_data.get("persian_quality_score"),
                "quality_status": cand_data.get("quality_status", "pending"),
                "judge_votes_json": votes_json,
                "consensus_status": cand_data.get("consensus_status"),
                "final_label": cand_data.get("final_label"),
                "final_status": cand_data.get("final_status", "unresolved"),
                "flags_json": flags_json,
                "reason": cand_data.get("reason"),
                "generator_model": cand_data.get("generator_model"),
                "human_decision": cand_data.get("human_decision"),
                "human_edited_text": cand_data.get("human_edited_text"),
                "human_notes": cand_data.get("human_notes"),
                "reviewer_name": cand_data.get("reviewer_name"),
                "updated_at_utc": now
            })

    def record_attempt(
        self,
        candidate_id: str,
        step: str,
        model: str,
        usage: Dict[str, int],
        latency_sec: float,
        raw_completion: str,
        parsed_json: Optional[Dict[str, Any]],
        status: str,
        error_message: Optional[str] = None
    ) -> None:
        conn = self._get_connection()
        now = datetime.now(timezone.utc).isoformat()
        with conn:
            conn.execute("""
            INSERT INTO attempts (
                candidate_id, step, model, prompt_tokens, completion_tokens, total_tokens,
                latency_sec, raw_completion, parsed_json, status, error_message, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                candidate_id,
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

    def fetch_all_candidates(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM candidates ORDER BY id;")
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            if d.get("judge_votes_json"):
                try:
                    d["judge_votes"] = json.loads(d["judge_votes_json"])
                except Exception:
                    d["judge_votes"] = None
            if d.get("flags_json"):
                try:
                    d["flags"] = json.loads(d["flags_json"])
                except Exception:
                    d["flags"] = []
            results.append(d)
        return results

    def fetch_all_attempts(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM attempts ORDER BY id;")
        return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None
