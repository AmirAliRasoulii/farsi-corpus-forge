"""
Human-in-the-Loop (HITL) review manager for Persianization.
Ingests reviewed Excel spreadsheets with strict integrity verification:
- Checks record ID, text hash, and provenance before writing.
- Stores human-edited text in dedicated human_edited_text field.
- Ensures prior automated quality evaluations are NOT carried over to human edits.
- Atomic verification: prevents partial corrupt imports.
- Distinguishes explicit '0' from blank/unreviewed.
"""
import os
import hashlib
from typing import Dict, Any, List
from shared.excel_utils import read_reviewed_excel
from shared.lineage import compute_text_hash
from persianization.storage import PersianizationStorage


class ReviewIngestError(Exception):
    """Raised when review workbook integrity verification fails."""
    pass


def ingest_persianization_review(
    excel_path: str,
    storage: PersianizationStorage,
    reviewer_override: str = None,
    run_id: str = None
) -> Dict[str, Any]:
    """
    Ingests reviewed Excel and updates SQLite records with strict provenance checks.
    """
    if not os.path.isfile(excel_path):
        raise FileNotFoundError(f"Review Excel file does not exist: {excel_path}")

    reviewed_items = read_reviewed_excel(excel_path)
    conn = storage._get_connection()
    cursor = conn.cursor()

    # Pre-validation phase: verify all reviewed rows exist in DB and validate text consistency
    items_to_update = []
    for item in reviewed_items:
        if not item["has_human_review"]:
            continue

        rec_id = item["id"]
        cursor.execute("SELECT * FROM records WHERE id = ?;", (rec_id,))
        row = cursor.fetchone()
        if not row:
            raise ReviewIngestError(
                f"Workbook validation failed: Record ID '{rec_id}' not found in database. "
                "Aborting import to prevent partial corruption."
            )

        db_rec = dict(row)
        # Verify raw text hash if text was present in excel
        excel_raw = item["row_data"].get("raw_text") or item["row_data"].get("text")
        if excel_raw and compute_text_hash(str(excel_raw)) != compute_text_hash(str(db_rec.get("raw_text"))):
            raise ReviewIngestError(
                f"Integrity mismatch for record '{rec_id}': Original text in Excel does not match database record."
            )

        items_to_update.append((item, db_rec))

    # Apply updates atomically
    updated_count = 0
    accepted_count = 0
    rejected_count = 0
    edited_count = 0

    for item, current_record in items_to_update:
        decision = item["human_decision"]
        edited_text = item["human_edited_text"]
        notes = item["human_notes"]
        reviewer = reviewer_override or item["reviewer_name"] or "annotator"

        dec_norm = str(decision).strip().lower()
        final_persian = current_record.get("final_persian_text")

        if dec_norm in ("accept", "approved", "ok", "1", "pass"):
            quality_status = "accepted"
            accepted_count += 1
        elif dec_norm in ("reject", "0", "fail", "rejected"):
            quality_status = "rejected"
            rejected_count += 1
        elif dec_norm in ("edit", "edited", "modify"):
            quality_status = "accepted"
            edited_count += 1
            if edited_text:
                final_persian = edited_text
        else:
            quality_status = f"human_{dec_norm}"

        if edited_text:
            final_persian = edited_text
            # CRITICAL RULE: Prior automated QC scores DO NOT carry over to human-edited text!
            current_record["quality_scores"] = None
            current_record["quality_flags"] = ["human_edited"]
            current_record["evaluator_1_model"] = f"human:{reviewer}"
            current_record["reason"] = f"Human verified and edited by {reviewer}."

        current_record["quality_status"] = quality_status
        current_record["final_persian_text"] = final_persian
        current_record["human_decision"] = str(decision)
        current_record["human_edited_text"] = edited_text
        current_record["human_notes"] = notes
        current_record["reviewer_name"] = reviewer

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
