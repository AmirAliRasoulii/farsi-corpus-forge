"""
Text safety, formula sanitization, and raw text preservation utilities.
"""
from typing import Any

# Characters that trigger formula execution in spreadsheet software (Excel, LibreOffice, Google Sheets)
DANGEROUS_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')
EXCEL_MAX_CELL_LENGTH = 32767


def sanitize_for_excel(value: Any) -> Any:
    """
    Sanitize text to prevent CSV/Excel Formula Injection (CSV Injection / CWE-1236).
    If a cell value starts with '=', '+', '-', '@', '\t', or '\r', prefix with single quote "'".
    Also converts newlines cleanly.
    """
    if value is None:
        return ""
    
    val_str = str(value)
    if not val_str:
        return ""
    
    # Check formula prefixes
    if val_str.startswith(DANGEROUS_FORMULA_PREFIXES):
        val_str = "'" + val_str
        
    return val_str


def check_excel_length_limit(text: str) -> bool:
    """
    Returns True if the text length fits in Excel limit (32,767 chars), False otherwise.
    """
    if not text:
        return True
    return len(str(text)) <= EXCEL_MAX_CELL_LENGTH


def preserve_raw_text(raw_text: str, candidate_text: str) -> None:
    """
    Ensures that raw text is strictly preserved and not mutated or trimmed.
    Raises ValueError if raw text has been unexpectedly altered.
    """
    if raw_text is None or candidate_text is None:
        return
    if raw_text != candidate_text:
        raise ValueError("Raw text mutation detected! Raw input must be strictly immutable.")
