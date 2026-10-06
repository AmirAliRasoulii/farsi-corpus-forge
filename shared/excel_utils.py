"""
Excel export and review ingestion utilities with formula injection protection,
visual status styling, and strict schema validation.
"""
import os
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from shared.text_safety import sanitize_for_excel, check_excel_length_limit, EXCEL_MAX_CELL_LENGTH


# Color Fills for Visual Status
COLOR_FILLS = {
    "green": PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid"),   # Accepted / Verified
    "orange": PatternFill(start_color="FFE8D6", end_color="FFE8D6", fill_type="solid"),  # Review required / QC flag
    "yellow": PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid"),  # Uncertain / Ambiguous
    "red": PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid"),      # Refused / Failed / Unable
    "header": PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")   # Header row dark navy
}

HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
REGULAR_FONT = Font(name="Calibri", size=10)
BOLD_FONT = Font(name="Calibri", size=10, bold=True)


def determine_row_status_color(status: str, flags: Optional[List[str]] = None) -> Optional[str]:
    """
    Determines color tag based on explicit status string and flags.
    Color is accompanied by explicit status text columns.
    """
    st = str(status).lower()
    fl = [f.lower() for f in (flags or [])]

    if "refuse" in st or "fail" in st or "unable" in st or "error" in st:
        return "red"
    if "uncertain" in st or "ambiguous" in st or "unresolved" in st or "tie" in st:
        return "yellow"
    if "review" in st or "audit" in st or any("changed" in f or "censored" in f or "awkward" in f for f in fl):
        return "orange"
    if "accepted" in st or "native_fa" in st or "approved" in st:
        return "green"
    return None


def export_records_to_excel(
    records: List[Dict[str, Any]],
    output_path: str,
    sheet_title: str = "Records",
    columns: Optional[List[str]] = None,
    include_hitl_columns: bool = True
) -> str:
    """
    Exports a list of records to a formatted Excel file with:
    - Formula injection defense
    - Color styling according to status
    - Editable green review columns for Human-in-the-Loop (HITL)
    - Cell length warning note if content exceeds Excel limit
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title

    if not records:
        ws.append(["No records available"])
        wb.save(output_path)
        return output_path

    # Determine columns
    if columns is None:
        standard_order = [
            "id", "status", "origin", "language", "text", "context",
            "text_fa", "context_fa", "quality_score", "flags", "reason"
        ]
        sample_keys = list(records[0].keys())
        columns = [c for c in standard_order if c in sample_keys]
        for k in sample_keys:
            if k not in columns and not k.startswith("_"):
                columns.append(k)

    # Human-in-the-loop review columns
    hitl_cols = [
        "human_decision",      # 'accept', 'reject', 'edited' (or '0' / '1' for label)
        "human_edited_text",   # Edited text if modified
        "human_notes",         # Notes / reviewer reason
        "reviewer_name"        # Name or ID of reviewer
    ]

    all_headers: List[str] = []
    seen_headers = set()
    for col in columns:
        if col not in seen_headers:
            all_headers.append(col)
            seen_headers.add(col)

    if include_hitl_columns:
        for hc in hitl_cols:
            if hc not in seen_headers:
                all_headers.append(hc)
                seen_headers.add(hc)

    ws.append(all_headers)

    # Style header row
    for col_idx in range(1, len(all_headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = HEADER_FONT
        cell.fill = COLOR_FILLS["header"]
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    has_exceeded_length = False

    # Write records
    for row_idx, rec in enumerate(records, start=2):
        row_status = (
            rec.get("quality_status") or
            rec.get("status") or
            rec.get("translation_status") or
            rec.get("final_status") or
            rec.get("annotation_status", "")
        )
        raw_flags = rec.get("quality_flags") or rec.get("flags") or []
        if isinstance(raw_flags, str):
            flags_list = [raw_flags]
        elif isinstance(raw_flags, list):
            flags_list = raw_flags
        else:
            flags_list = []

        color_tag = determine_row_status_color(str(row_status), flags_list)
        row_fill = COLOR_FILLS.get(color_tag) if color_tag else None

        for col_idx, col_name in enumerate(all_headers, start=1):
            val = rec.get(col_name)
            if isinstance(val, (dict, list)):
                import json
                val = json.dumps(val, ensure_ascii=False)

            val_str = str(val) if val is not None else ""
            if not check_excel_length_limit(val_str):
                has_exceeded_length = True

            # Sanitize against CSV/Excel formula injection
            sanitized_val = sanitize_for_excel(val)
            cell = ws.cell(row=row_idx, column=col_idx, value=sanitized_val)
            cell.font = REGULAR_FONT
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if row_fill and col_name in ("id", "status", "quality_status", "translation_status", "flags", "quality_flags", "reason"):
                cell.fill = row_fill

    # Add warning banner if length exceeded
    if has_exceeded_length:
        ws.insert_rows(1)
        warning_cell = ws.cell(row=1, column=1, value=(
            f"WARNING: One or more text fields exceeded Excel's maximum cell display limit ({EXCEL_MAX_CELL_LENGTH} characters). "
            "Please refer to the authoritative JSONL files for full un-truncated text."
        ))
        warning_cell.font = Font(name="Calibri", size=11, bold=True, color="721C24")
        warning_cell.fill = COLOR_FILLS["red"]

    # Adjust column widths
    for col_cells in ws.columns:
        col_letter = get_column_letter(col_cells[0].column)
        max_len = 0
        for c in col_cells[:50]:  # check sample
            v = str(c.value or "")
            if len(v) > max_len:
                max_len = len(v)
        ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)

    wb.save(output_path)
    return output_path


def read_reviewed_excel(
    filepath: str,
    expected_run_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Ingests reviewed Excel spreadsheet with validation:
    - Reads human decisions and edits
    - Distinguishes explicit '0' from empty/unreviewed!
    - Verifies record structure
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Review Excel file not found: {filepath}")

    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active

    headers = [cell.value for cell in ws[1] if cell.value is not None]
    if not headers:
        raise ValueError("Excel file is empty or missing headers.")

    cleaned_headers = [str(h).strip() for h in headers]
    if len(cleaned_headers) != len(set(cleaned_headers)):
        seen = set()
        duplicates = set()
        for h in cleaned_headers:
            if h in seen:
                duplicates.add(h)
            seen.add(h)
        raise ValueError(f"Excel file contains duplicate header columns: {sorted(list(duplicates))}")

    header_to_col = {h: idx for idx, h in enumerate(cleaned_headers, start=1)}
    
    if "id" not in header_to_col:
        raise ValueError("Excel file is missing required 'id' column.")

    reviewed_records = []
    start_row = 2

    for r_idx in range(start_row, ws.max_row + 1):
        rec_id = ws.cell(row=r_idx, column=header_to_col["id"]).value
        if rec_id is None or not str(rec_id).strip():
            continue

        row_data = {}
        for h, c_idx in header_to_col.items():
            cell_val = ws.cell(row=r_idx, column=c_idx).value
            # Strip Excel escape prefix if present
            if isinstance(cell_val, str) and cell_val.startswith("'"):
                cell_val = cell_val[1:]
            row_data[h] = cell_val

        # Extract human review fields
        decision = row_data.get("human_decision")
        edited_text = row_data.get("human_edited_text")
        notes = row_data.get("human_notes")
        reviewer = row_data.get("reviewer_name")

        # Crucial requirement: Distinguish '0' from None/empty!
        has_human_review = False
        decision_val = None
        if decision is not None:
            dec_str = str(decision).strip()
            if dec_str != "":
                has_human_review = True
                decision_val = dec_str

        reviewed_records.append({
            "id": str(rec_id).strip(),
            "has_human_review": has_human_review,
            "human_decision": decision_val,
            "human_edited_text": str(edited_text).strip() if edited_text else None,
            "human_notes": str(notes).strip() if notes else None,
            "reviewer_name": str(reviewer).strip() if reviewer else "anonymous",
            "reviewed_at_utc": datetime.now(timezone.utc).isoformat() if has_human_review else None,
            "row_data": row_data
        })

    return reviewed_records
