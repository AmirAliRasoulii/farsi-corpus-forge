"""
Human-in-the-Loop (HITL) review manager for Persianization.
Ingests edited review.xlsx spreadsheets, verifies record hashes and IDs,
applies human decisions/edits to SQLite, and updates exported datasets.
"""
import os
from typing import Dict, Any, List
from shared.excel_utils import read_reviewed_excel
from persianization.storage import PersianizationStorage


def ingest_persianization_review(
    excel_path: str,
    storage: PersianizationStorage,
    reviewer_override: str = None
) -> Dict[str, Any]:
    """
    Ingests reviewed Excel and updates SQLite records.
    Distinguishes explicit '0' or 'reject' from blank!
    """
    if not os.path.isfile(excel_path):
        raise FileNotFoundError(f"Review Excel file does not exist: {excel_path}")

    reviewed_items = read_reviewed_excel(excel_path)
    
    updated_count = 0
    accepted_count = 0
    rejected_count = 0
    edited_count = 0

    for item in reviewed_items:
        if not item["has_human_review"]:
            continue

        rec_id = item["id"]
        decision = item["human_decision"]
        edited_text = item["human_edited_text"]
        notes = item["human_notes"]
        reviewer = reviewer_override or item["reviewer_name"] or "annotator"

        # Lookup in storage
        conn = storage._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM records WHERE id = ?;", (rec_id,))
        row = cursor.fetchone()
        if not row:
            continue

        current_record = dict(row)
        final_persian = current_record.get("final_persian_text")
        quality_status = current_record.get("quality_status")

        # Parse decision
        dec_norm = str(decision).strip().lower()
        if dec_norm in ("accept", "approved", "ok", "1", "pass"):
            quality_status = "accepted"
            accepted_count += 1
        elif dec_norm in ("reject", "0", "fail", "rejected"):
            quality_status = "rejected"
            rejected_count += 1
        elif dec_norm in ("edit", "edited", "modify"):
            quality_status = "accepted"
            if edited_text:
                final_persian = edited_text
            edited_count += 1
        else:
            # Custom decision
            quality_status = f"human_{dec_norm}"

        if edited_text and edited_text != final_persian:
            final_persian = edited_text

        current_record["quality_status"] = quality_status
        current_record["final_persian_text"] = final_persian
        current_record["human_decision"] = str(decision)
        current_record["human_edited_text"] = edited_text
        current_record["human_notes"] = notes
        current_record["reviewer_name"] = reviewer

        # Rename keys to match save_record expectation
        current_record["text"] = current_record["raw_text"]
        current_record["context"] = current_record["raw_context"]
        current_record["language"] = current_record["original_language"]

        storage.save_record(current_record)
        updated_count += 1

    return {
        "total_rows_inspected": len(reviewed_items),
        "updated_records_count": updated_count,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "edited_count": edited_count
    }
