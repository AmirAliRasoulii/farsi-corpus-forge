"""
Tests for input validation, file formats (CSV, JSON, JSONL), and duplicate key detection.
"""
import os
import json
import tempfile
import pytest
from shared.io_utils import (
    stream_input_records,
    InputValidationError,
    check_duplicate_json_keys
)


def test_empty_text_rejected():
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write('{"id": "1", "text": "   "}\n')
        temp_path = f.name

    try:
        with pytest.raises(InputValidationError) as exc:
            list(stream_input_records(temp_path))
        assert "empty or non-string" in str(exc.value)
    finally:
        os.remove(temp_path)


def test_duplicate_record_id_rejected():
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write('{"id": "duplicate_id", "text": "متن اول"}\n')
        f.write('{"id": "duplicate_id", "text": "متن دوم"}\n')
        temp_path = f.name

    try:
        with pytest.raises(InputValidationError) as exc:
            list(stream_input_records(temp_path))
        assert "Duplicate record ID" in str(exc.value)
    finally:
        os.remove(temp_path)


def test_duplicate_csv_header_rejected():
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write("id,text,text\n1,سلام,سلام مجدد\n")
        temp_path = f.name

    try:
        with pytest.raises(InputValidationError) as exc:
            list(stream_input_records(temp_path))
        assert "Duplicate CSV header column" in str(exc.value)
    finally:
        os.remove(temp_path)


def test_csv_row_column_mismatch_rejected():
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write("id,text,source\n1,سلام,منبع\n2,سلام,منبع,اضافه\n")
        temp_path = f.name

    try:
        with pytest.raises(InputValidationError) as exc:
            list(stream_input_records(temp_path))
        assert "expected 3" in str(exc.value) or "Corrupt CSV row structure" in str(exc.value)
    finally:
        os.remove(temp_path)


def test_duplicate_json_keys_rejected():
    raw_json = '{"id": "1", "text": "اول", "text": "دوم"}'
    with pytest.raises(ValueError) as exc:
        json.loads(raw_json, object_pairs_hook=check_duplicate_json_keys)
    assert "Duplicate JSON key" in str(exc.value)


def test_format_parity_csv_json_jsonl():
    """Verifies that CSV, JSON, and JSONL produce identical standardized records."""
    csv_content = 'id,text,language,split\nrec_1,"متن تستی",fa,train\n'
    json_content = '[{"id": "rec_1", "text": "متن تستی", "language": "fa", "split": "train"}]'
    jsonl_content = '{"id": "rec_1", "text": "متن تستی", "language": "fa", "split": "train"}\n'

    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f_csv:
        f_csv.write(csv_content)
        path_csv = f_csv.name

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f_json:
        f_json.write(json_content)
        path_json = f_json.name

    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f_jsonl:
        f_jsonl.write(jsonl_content)
        path_jsonl = f_jsonl.name

    try:
        rec_csv = list(stream_input_records(path_csv))[0]
        rec_json = list(stream_input_records(path_json))[0]
        rec_jsonl = list(stream_input_records(path_jsonl))[0]

        for k in ("id", "text", "language", "split"):
            assert rec_csv[k] == rec_json[k] == rec_jsonl[k]
    finally:
        os.remove(path_csv)
        os.remove(path_json)
        os.remove(path_jsonl)
