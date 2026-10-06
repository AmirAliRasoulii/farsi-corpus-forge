"""
HITL Review manager for Project B (White Generation).
Ingests human decisions from Excel, verifies candidates, and updates SQLite checkpoint.
"""
import os
from typing import Dict, Any, List
from shared.excel_utils import read_reviewed_excel
from white_generation.storage import WhiteGenerationStorage


def ingest_white_generation_review(
    excel_path: str,
    storage: WhiteGenerationStorage,
    reviewer_override: str = None
) -> Dict[str, Any]:
    """
    Ingests reviewed Excel and updates candidate records.
    Distinguishes explicit '0' or 'accept' from unreviewed blank!
    """
    if not os.path.isfile(excel_path):
        raise FileNotFoundError(f"Excel review file not found: {excel_path}")

    reviewed_items = read_reviewed_excel(excel_path)
    updated_count = 0
    accepted_count = 0
    rejected_count = 0

    conn = storage._get_connection()

    for item in reviewed_items:
        if not item["has_human_review"]:
            continue

        cand_id = item["id"]
        decision = item["human_decision"]
        edited_text = item["human_edited_text"]
        notes = item["human_notes"]
        reviewer = reviewer_override or item["reviewer_name"] or "annotator"

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM candidates WHERE id = ?;", (cand_id,))
        row = cursor.fetchone()
        if not row:
            continue

        cand_record = dict(row)
        dec_norm = str(decision).strip().lower()

        if dec_norm in ("accept", "0", "clean", "pass", "approved"):
            cand_record["final_status"] = "accepted_white"
            cand_record["final_label"] = 0
            accepted_count += 1
        elif dec_norm in ("reject", "1", "offensive", "fail"):
            cand_record["final_status"] = "rejected"
            cand_record["final_label"] = 1
            rejected_count += 1
        else:
            cand_record["final_status"] = f"human_{dec_norm}"

        if edited_text:
            cand_record["candidate_text"] = edited_text

        cand_record["human_decision"] = str(decision)
        cand_record["human_edited_text"] = edited_text
        cand_record["human_notes"] = notes
        cand_record["reviewer_name"] = reviewer

        storage.save_candidate(cand_record)
        updated_count += 1

    return {
        "total_rows_inspected": len(reviewed_items),
        "updated_candidates_count": updated_count,
        "accepted_white_count": accepted_count,
        "rejected_count": rejected_count
    }
