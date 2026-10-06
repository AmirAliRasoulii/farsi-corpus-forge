"""
Input/Output utilities for CSV (UTF-8 / BOM), JSON, and JSONL.
Includes strict pre-API validation, streaming generators, duplicate key detection,
and immutable raw text handling.
"""
import os
import csv
import json
import codecs
import unicodedata
from typing import Generator, Dict, Any, List, Optional, Tuple, Set


class InputValidationError(Exception):
    """Raised when pre-API input data validation fails."""
    def __init__(self, message: str, row_index: Optional[int] = None, record_id: Optional[str] = None):
        super().__init__(message)
        self.row_index = row_index
        self.record_id = record_id


def check_duplicate_json_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    """Custom decoder hook for json.loads that raises ValueError on duplicate keys."""
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError(f"Duplicate JSON key found in object: '{k}'")
        d[k] = v
    return d


def detect_file_encoding(filepath: str) -> str:
    """Detects if file starts with UTF-8 BOM, otherwise defaults to utf-8."""
    with open(filepath, 'rb') as f:
        raw_start = f.read(4)
        if raw_start.startswith(codecs.BOM_UTF8):
            return 'utf-8-sig'
    return 'utf-8'


def normalize_persian_nfc(text: Optional[str]) -> Optional[str]:
    """
    Normalizes Persian text for auxiliary search/filtering in NFC form with ZWNJ standardization.
    IMPORTANT: This is only stored in normalized_* fields; raw text is NEVER overwritten!
    """
    if text is None:
        return None
    # Standardize to Unicode NFC
    norm = unicodedata.normalize('NFC', str(text))
    # Replace Arabic Kaf with Persian Kaf, Arabic Yeh with Persian Yeh
    norm = norm.replace('\u0643', '\u06a9').replace('\u0649', '\u06cc').replace('\u064a', '\u06cc')
    return norm


def stream_input_records(
    filepath: str,
    column_mapping: Optional[Dict[str, str]] = None,
    default_split: str = "unassigned"
) -> Generator[Dict[str, Any], None, None]:
    """
    Streams records from CSV, JSON, or JSONL with strict pre-API validation.
    Yields standardized dicts without holding entire dataset in memory.
    
    Standardized fields:
      - id: str
      - text: str (raw, immutable)
      - language: Optional[str]
      - context: Optional[str] (raw, immutable)
      - source: Optional[str]
      - source_label: Any
      - parent_id: Optional[str]
      - group_id: str
      - split: str
      - metadata: Dict[str, Any]
      - normalized_text: Optional[str] (separate auxiliary field)
      - normalized_context: Optional[str] (separate auxiliary field)
      - _raw_row_index: int
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Input file not found: {filepath}")

    ext = os.path.splitext(filepath)[1].lower()
    col_map = column_mapping or {}
    text_col = col_map.get("text", "text")
    id_col = col_map.get("id", "id")
    lang_col = col_map.get("language", "language")
    context_col = col_map.get("context", "context")
    source_col = col_map.get("source", "source")
    source_label_col = col_map.get("source_label", "source_label")
    parent_id_col = col_map.get("parent_id", "parent_id")
    group_id_col = col_map.get("group_id", "group_id")
    split_col = col_map.get("split", "split")
    meta_col = col_map.get("metadata", "metadata")

    seen_ids: Set[str] = set()
    encoding = detect_file_encoding(filepath)

    if ext in ('.csv', '.tsv'):
        delimiter = '\t' if ext == '.tsv' else ','
        with open(filepath, 'r', encoding=encoding, newline='') as f:
            reader = csv.reader(f, delimiter=delimiter)
            try:
                headers = next(reader)
            except StopIteration:
                return  # Empty file

            # Check duplicate CSV header columns
            seen_headers = set()
            for h in headers:
                h_stripped = h.strip()
                if h_stripped in seen_headers:
                    raise InputValidationError(f"Duplicate CSV header column detected: '{h_stripped}'", row_index=1)
                seen_headers.add(h_stripped)

            if text_col not in seen_headers:
                raise InputValidationError(f"Mandatory text column '{text_col}' not found in CSV headers: {headers}", row_index=1)

            header_to_idx = {h.strip(): i for i, h in enumerate(headers)}
            expected_col_count = len(headers)

            for row_idx, row in enumerate(reader, start=2):
                if not row or all(not cell.strip() for cell in row):
                    # Empty row
                    continue

                if len(row) != expected_col_count:
                    raise InputValidationError(
                        f"Row has {len(row)} values, expected {expected_col_count}. Corrupt CSV row structure.",
                        row_index=row_idx
                    )

                raw_data = {h.strip(): row[i] for h, i in header_to_idx.items()}
                record = _standardize_and_validate_record(
                    raw_data=raw_data,
                    row_idx=row_idx,
                    seen_ids=seen_ids,
                    text_col=text_col,
                    id_col=id_col,
                    lang_col=lang_col,
                    context_col=context_col,
                    source_col=source_col,
                    source_label_col=source_label_col,
                    parent_id_col=parent_id_col,
                    group_id_col=group_id_col,
                    split_col=split_col,
                    meta_col=meta_col,
                    default_split=default_split
                )
                yield record

    elif ext == '.jsonl' or ext == '.ndjson':
        with open(filepath, 'r', encoding=encoding) as f:
            for row_idx, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    raw_data = json.loads(stripped, object_pairs_hook=check_duplicate_json_keys)
                except ValueError as e:
                    raise InputValidationError(f"Invalid JSON at line {row_idx}: {str(e)}", row_index=row_idx)

                if not isinstance(raw_data, dict):
                    raise InputValidationError(f"Expected JSON object at line {row_idx}, got {type(raw_data).__name__}", row_index=row_idx)

                record = _standardize_and_validate_record(
                    raw_data=raw_data,
                    row_idx=row_idx,
                    seen_ids=seen_ids,
                    text_col=text_col,
                    id_col=id_col,
                    lang_col=lang_col,
                    context_col=context_col,
                    source_col=source_col,
                    source_label_col=source_label_col,
                    parent_id_col=parent_id_col,
                    group_id_col=group_id_col,
                    split_col=split_col,
                    meta_col=meta_col,
                    default_split=default_split
                )
                yield record

    elif ext == '.json':
        # May be a list of records or single object
        with open(filepath, 'r', encoding=encoding) as f:
            content = f.read()
            try:
                data = json.loads(content, object_pairs_hook=check_duplicate_json_keys)
            except ValueError as e:
                raise InputValidationError(f"Invalid JSON: {str(e)}", row_index=1)

            if isinstance(data, dict):
                # Might have an inner key or be single record
                if "records" in data and isinstance(data["records"], list):
                    records_list = data["records"]
                elif "data" in data and isinstance(data["data"], list):
                    records_list = data["data"]
                else:
                    records_list = [data]
            elif isinstance(data, list):
                records_list = data
            else:
                raise InputValidationError(f"JSON root must be an array or object, got {type(data).__name__}")

            for row_idx, raw_data in enumerate(records_list, start=1):
                if not isinstance(raw_data, dict):
                    raise InputValidationError(f"Record at index {row_idx} must be a dict, got {type(raw_data).__name__}", row_index=row_idx)

                record = _standardize_and_validate_record(
                    raw_data=raw_data,
                    row_idx=row_idx,
                    seen_ids=seen_ids,
                    text_col=text_col,
                    id_col=id_col,
                    lang_col=lang_col,
                    context_col=context_col,
                    source_col=source_col,
                    source_label_col=source_label_col,
                    parent_id_col=parent_id_col,
                    group_id_col=group_id_col,
                    split_col=split_col,
                    meta_col=meta_col,
                    default_split=default_split
                )
                yield record
    else:
        raise ValueError(f"Unsupported file format: {ext}. Supported formats: .csv, .tsv, .json, .jsonl, .ndjson")


def _standardize_and_validate_record(
    raw_data: Dict[str, Any],
    row_idx: int,
    seen_ids: Set[str],
    text_col: str,
    id_col: str,
    lang_col: str,
    context_col: str,
    source_col: str,
    source_label_col: str,
    parent_id_col: str,
    group_id_col: str,
    split_col: str,
    meta_col: str,
    default_split: str
) -> Dict[str, Any]:
    """Validates raw row and constructs standardized record object without mutating raw text."""
    # 1. Text validation
    if text_col not in raw_data:
        # Check common fallback text column aliases
        fallback_found = None
        for cand_col in ("text", "final_persian_text", "raw_text", "sentence", "content"):
            if cand_col in raw_data:
                fallback_found = cand_col
                break
        if fallback_found:
            text_col = fallback_found
        else:
            raise InputValidationError(f"Row {row_idx} is missing mandatory '{text_col}' field.", row_index=row_idx)

    raw_text = raw_data[text_col]
    if raw_text is None or not isinstance(raw_text, str) or not raw_text.strip():
        raise InputValidationError(
            f"Row {row_idx} has empty or non-string '{text_col}' field (value: {repr(raw_text)}).",
            row_index=row_idx
        )

    # 2. ID validation & deduplication
    rec_id = raw_data.get(id_col)
    if rec_id is None or str(rec_id).strip() == "":
        rec_id = f"row_{row_idx}"
    else:
        rec_id = str(rec_id).strip()

    if rec_id in seen_ids:
        raise InputValidationError(f"Duplicate record ID '{rec_id}' encountered at row {row_idx}.", row_index=row_idx, record_id=rec_id)
    seen_ids.add(rec_id)

    # 3. Optional fields
    raw_context = raw_data.get(context_col)
    if raw_context is not None:
        raw_context = str(raw_context)

    language = raw_data.get(lang_col)
    if language is not None:
        language = str(language).strip()
    else:
        language = None

    source = raw_data.get(source_col)
    if source is not None:
        source = str(source).strip()

    source_label = raw_data.get(source_label_col)

    parent_id = raw_data.get(parent_id_col)
    if parent_id is not None:
        parent_id = str(parent_id).strip()

    group_id = raw_data.get(group_id_col)
    if group_id is not None and str(group_id).strip():
        group_id = str(group_id).strip()
    else:
        group_id = parent_id if parent_id else rec_id

    split = raw_data.get(split_col)
    if split is not None and str(split).strip():
        split = str(split).strip()
    else:
        split = default_split

    metadata = raw_data.get(meta_col)
    if metadata is not None and isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {"raw_metadata_string": metadata}
    elif metadata is None:
        # Collect unmapped keys as extra metadata
        known_keys = {text_col, id_col, lang_col, context_col, source_col, source_label_col, parent_id_col, group_id_col, split_col, meta_col}
        extra_keys = {k: v for k, v in raw_data.items() if k not in known_keys}
        metadata = extra_keys if extra_keys else {}
    elif not isinstance(metadata, dict):
        metadata = {"val": metadata}

    return {
        "id": rec_id,
        "text": raw_text,  # STRICTLY PRESERVED RAW TEXT
        "language": language,
        "context": raw_context,  # STRICTLY PRESERVED RAW CONTEXT
        "source": source,
        "source_label": source_label,
        "parent_id": parent_id,
        "group_id": group_id,
        "split": split,
        "metadata": metadata,
        "normalized_text": normalize_persian_nfc(raw_text),
        "normalized_context": normalize_persian_nfc(raw_context) if raw_context else None,
        "_raw_row_index": row_idx
    }
