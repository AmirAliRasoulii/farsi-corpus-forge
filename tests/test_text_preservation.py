"""
Unit tests for raw text preservation and Excel sanitization.
"""
import pytest
from shared.text_safety import sanitize_for_excel, preserve_raw_text
from shared.io_utils import normalize_persian_nfc


def test_raw_text_strict_preservation():
    complex_raw = '  "Hello!!!"  این یک متن با ایموجی 😡 و ناسزای پوشیده f**k و فاصله است.  '
    # Test immutability helper
    preserve_raw_text(complex_raw, complex_raw)

    with pytest.raises(ValueError):
        preserve_raw_text(complex_raw, complex_raw.strip())


def test_normalization_in_auxiliary_field_only():
    raw = "يک متن با ي و ك عربي"
    normalized = normalize_persian_nfc(raw)
    assert "ی" in normalized
    assert "ک" in normalized
    # Raw must remain completely untouched
    assert raw != normalized


def test_excel_formula_sanitization():
    dangerous_inputs = [
        "=SUM(A1:A10)",
        "+cmd|' /C calc'!A0",
        "-12345",
        "@SUM(B1:B2)",
        "\tleading_tab",
        "\rleading_cr"
    ]
    for inp in dangerous_inputs:
        sanitized = sanitize_for_excel(inp)
        assert sanitized.startswith("'")
