"""
Tests for strict model output schema validation.
"""
import pytest
from shared.schema_validator import (
    validate_translator_output,
    validate_quality_judge_output,
    validate_offense_judge_output,
    validate_generator_output,
    SchemaValidationError
)


def test_schema_validator_rejects_non_dict_root():
    for non_dict in ([{"label": 0}], "string response", 123, None):
        with pytest.raises(SchemaValidationError, match="must be a JSON object"):
            validate_translator_output(non_dict)
        with pytest.raises(SchemaValidationError, match="must be a JSON object"):
            validate_quality_judge_output(non_dict)
        with pytest.raises(SchemaValidationError, match="must be a JSON object"):
            validate_offense_judge_output(non_dict)
        with pytest.raises(SchemaValidationError, match="must be a JSON object"):
            validate_generator_output(non_dict)


def test_translator_output_validation():
    # Valid
    valid = validate_translator_output({
        "status": "translated",
        "text_fa": "متن ترجمه شده",
        "context_fa": None,
        "reason": "OK"
    })
    assert valid["status"] == "translated"
    assert valid["text_fa"] == "متن ترجمه شده"

    # Missing text_fa on translated status
    with pytest.raises(SchemaValidationError, match="text_fa"):
        validate_translator_output({"status": "translated", "text_fa": None})

    # Empty string text_fa on translated status
    with pytest.raises(SchemaValidationError, match="text_fa"):
        validate_translator_output({"status": "translated", "text_fa": "  "})

    # Invalid status
    with pytest.raises(SchemaValidationError, match="status"):
        validate_translator_output({"status": "unknown_status"})


def test_quality_judge_output_validation():
    base = {
        "fluency": 5,
        "naturalness": 5,
        "register_match": 5,
        "cultural_fit": 5,
        "semantic_fidelity": 5,
        "severity_fidelity": 5,
        "context_fidelity": {"applicable": False, "score": None},
        "target_preserved": True,
        "stance_preserved": True,
        "negation_preserved": True,
        "quotation_preserved": True,
        "ambiguity_preserved": True,
        "flags": [],
        "reason": "Good"
    }
    # Valid
    res = validate_quality_judge_output(base)
    assert res["scores"]["fluency"] == 5

    # Out of range score (100)
    invalid_100 = dict(base, fluency=100)
    with pytest.raises(SchemaValidationError, match="fluency"):
        validate_quality_judge_output(invalid_100)

    # Score 0
    invalid_0 = dict(base, fluency=0)
    with pytest.raises(SchemaValidationError, match="fluency"):
        validate_quality_judge_output(invalid_0)

    # Float score (4.5)
    invalid_float = dict(base, fluency=4.5)
    with pytest.raises(SchemaValidationError, match="fluency"):
        validate_quality_judge_output(invalid_float)

    # Boolean score (True)
    invalid_bool = dict(base, fluency=True)
    with pytest.raises(SchemaValidationError, match="fluency"):
        validate_quality_judge_output(invalid_bool)

    # Missing preservation check
    missing_pres = dict(base)
    del missing_pres["ambiguity_preserved"]
    with pytest.raises(SchemaValidationError, match="ambiguity_preserved"):
        validate_quality_judge_output(missing_pres)

    # Non-boolean preservation check ("yes")
    non_bool_pres = dict(base, ambiguity_preserved="yes")
    with pytest.raises(SchemaValidationError, match="ambiguity_preserved"):
        validate_quality_judge_output(non_bool_pres)


def test_offense_judge_output_validation():
    # Valid 0 and 1
    valid0 = validate_offense_judge_output({"label": 0, "confidence": 0.95, "reason": "clean"})
    assert valid0["label"] == 0
    assert valid0["confidence"] == 0.95

    valid1 = validate_offense_judge_output({"label": 1, "confidence": 0.8, "reason": "offensive"})
    assert valid1["label"] == 1

    # Float label (0.8) must be rejected!
    with pytest.raises(SchemaValidationError, match="label"):
        validate_offense_judge_output({"label": 0.8, "confidence": 0.8})

    # Boolean label (True or False) must be rejected!
    with pytest.raises(SchemaValidationError, match="label"):
        validate_offense_judge_output({"label": True, "confidence": 0.8})

    with pytest.raises(SchemaValidationError, match="label"):
        validate_offense_judge_output({"label": False, "confidence": 0.8})

    # String label ("0" or "1") must be rejected!
    with pytest.raises(SchemaValidationError, match="label"):
        validate_offense_judge_output({"label": "0", "confidence": 0.8})

    # Confidence out of bounds (5.0, 100, -0.5) must be rejected!
    with pytest.raises(SchemaValidationError, match="confidence"):
        validate_offense_judge_output({"label": 0, "confidence": 5.0})

    with pytest.raises(SchemaValidationError, match="confidence"):
        validate_offense_judge_output({"label": 0, "confidence": -0.1})
