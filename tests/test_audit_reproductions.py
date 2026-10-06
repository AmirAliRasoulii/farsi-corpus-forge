"""
Reproduction tests for defects identified in the engineering audit.
These tests verify that the bugs are properly reproduced before fixes
and that the system enforces rigorous standards afterwards.
"""
import pytest
from shared.language_detector import detect_language
from persianization.router import route_record_languages
from shared.lineage import LineageTracker
from persianization.config import load_config
from white_generation.config import load_white_config, WhiteGenerationConfig


def test_reproduce_language_detection_common_words():
    """
    BUG: Short English sentences with shared words ('are', 'to', 'an')
    were misclassified as Fingilish even when declared_language='en'.
    """
    sentences = [
        "You are stupid.",
        "Go to hell!",
        "You are an idiot."
    ]
    for s in sentences:
        res = detect_language(s, declared_language="en")
        assert res["lang"] == "en", f"Sentence '{s}' was misclassified as '{res['lang']}' instead of 'en'"
        assert res["origin_status"] == "needs_translation_en_to_fa"

        routing = route_record_languages(s, declared_language="en")
        assert routing["origin"] == "translated_en_to_fa"
        assert routing["requires_text_translation"] is True
        assert routing["routing_status"] == "ready"


def test_reproduce_genuine_fingilish_still_detected():
    """Verify genuine Fingilish is still detected."""
    genuine_fingilish = [
        "salam chetori dash khobi?",
        "kheili mamnoon fadat besham azizam",
        "dada aslan nemikham biam damet garm"
    ]
    for s in genuine_fingilish:
        res = detect_language(s)
        assert res["lang"] == "fingilish"
        assert res["origin_status"] == "fingilish"


def test_reproduce_declared_language_script_conflict():
    """
    Conflict between declared language and actual script must trigger review.
    e.g. declared 'en' on Persian text, or declared 'fa' on English text.
    """
    res1 = detect_language("این یک متن فارسی است", declared_language="en")
    assert "language_script_conflict" in res1["flags"]
    assert res1["is_uncertain"] is True

    routing1 = route_record_languages("این یک متن فارسی است", declared_language="en")
    assert routing1["routing_status"] == "needs_review"


def test_reproduce_arabic_script_not_auto_persian():
    """
    Arabic text with distinct Arabic letters (ة, ك, ي with dots) should not be pure_persian_script.
    """
    arabic_text = "هذا نص باللغة العربية مع كلمات واضحة جداً"
    res = detect_language(arabic_text)
    # Should flag arabic features, not pure_persian_script
    assert "pure_persian_script" not in res["flags"]


def test_reproduce_white_generation_model_independence():
    """
    Model independence: judges must be 4 distinct models and neither judges nor quality evaluator may match generator.
    """
    config = load_white_config()
    # 1. Valid config should pass
    config.validate()

    # 2. Generator matching judge must fail validation
    config.judge_models[0] = config.generator_model
    with pytest.raises(ValueError, match="(?i)independence"):
        config.validate()

    # 3. Duplicate judges must fail validation
    config.judge_models = ["judge-a", "judge-a", "judge-b", "judge-c"]
    with pytest.raises(ValueError, match="(?i)independence"):
        config.validate()

    # 4. Generator matching quality evaluator must fail validation
    config.judge_models = ["judge-a", "judge-b", "judge-c", "judge-d"]
    config.quality_model = config.generator_model
    with pytest.raises(ValueError, match="(?i)independence"):
        config.validate()


def test_reproduce_cross_group_split_leakage():
    """
    BUG: Lineage tracker only checked split conflict within the same group_id.
    Identical text in different group_ids across train and test must be flagged!
    """
    tracker = LineageTracker()
    tracker.register_record(
        record_id="rec_tr_1",
        text="Unique insult sentence here.",
        group_id="group_A",
        split="train"
    )
    res2 = tracker.register_record(
        record_id="rec_te_1",
        text="Unique insult sentence here.",  # EXACT SAME TEXT
        group_id="group_B",                   # DIFFERENT GROUP
        split="test"                          # DIFFERENT SPLIT
    )
    assert res2["has_split_conflict"] is True
    report = tracker.get_leakage_report()
    assert report["family_split_conflicts_count"] > 0


def test_reproduce_quality_gate_context_fidelity_score_1(tmp_path):
    """
    BUG: When input has context, but model gives context_fidelity score 1,
    the candidate must NOT be accepted!
    """
    from persianization.storage import PersianizationStorage
    from persianization.quality_judge import DualQualityJudge
    from shared.api_client import AvalAIClient

    config = load_config()
    db_path = str(tmp_path / "qc_ctx.db")
    storage = PersianizationStorage(db_path)

    def mock_qc_with_low_ctx(model, messages, extra_params):
        data = {
            "fluency": 5,
            "naturalness": 5,
            "register_match": 5,
            "cultural_fit": 5,
            "semantic_fidelity": 5,
            "severity_fidelity": 5,
            "context_fidelity": {"applicable": True, "score": 1},  # CRITICAL FAILURE
            "target_preserved": True,
            "stance_preserved": True,
            "negation_preserved": True,
            "quotation_preserved": True,
            "ambiguity_preserved": True,
            "flags": ["context_distorted"],
            "reason": "Context distorted"
        }
        import json
        return {
            "raw_completion": json.dumps(data),
            "parsed_json": data,
            "usage": {}
        }

    client = AvalAIClient(api_key="mock", mock_handler=mock_qc_with_low_ctx)
    judge = DualQualityJudge(config, client, storage)

    res = judge.evaluate(
        record_id="rec_low_ctx",
        raw_text_en="Insult text",
        text_fa="متن توهین",
        raw_context_en="Important context",
        context_fa="زمینه تحریف‌شده",
        translator_model="mock-tr"
    )

    # Must NOT be accepted!
    assert res["quality_status"] != "accepted", "Candidate with context_fidelity=1 was falsely accepted!"
    assert res["quality_status"] in ("rejected", "review_required")


def test_reproduce_quality_gate_ambiguity_preserved_false(tmp_path):
    """
    BUG: When ambiguity_preserved is False, ambiguity_changed must block automated acceptance!
    """
    from persianization.storage import PersianizationStorage
    from persianization.quality_judge import DualQualityJudge
    from shared.api_client import AvalAIClient

    config = load_config()
    db_path = str(tmp_path / "qc_amb.db")
    storage = PersianizationStorage(db_path)

    def mock_qc_with_ambiguity_changed(model, messages, extra_params):
        data = {
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
            "ambiguity_preserved": False,  # AMBIGUITY RESOLVED BY GUESS
            "flags": ["ambiguity_changed"],
            "reason": "Ambiguity lost"
        }
        import json
        return {
            "raw_completion": json.dumps(data),
            "parsed_json": data,
            "usage": {}
        }

    client = AvalAIClient(api_key="mock", mock_handler=mock_qc_with_ambiguity_changed)
    judge = DualQualityJudge(config, client, storage)

    res = judge.evaluate(
        record_id="rec_amb",
        raw_text_en="Vague insult",
        text_fa="توهین بدون ابهام",
        raw_context_en=None,
        context_fa=None,
        translator_model="mock-tr"
    )

    assert res["quality_status"] != "accepted", "Candidate with ambiguity_preserved=False was falsely accepted!"
    assert res["quality_status"] in ("rejected", "review_required")


def test_reproduce_excel_duplicate_hitl_columns(tmp_path):
    """
    BUG: export_records_to_excel exported hitl_cols twice when records had those keys.
    Headers must be strictly unique!
    """
    from shared.excel_utils import export_records_to_excel
    import openpyxl

    out_file = str(tmp_path / "test_dup_cols.xlsx")
    records = [{
        "id": "rec_1",
        "text": "test",
        "human_decision": "accept",
        "human_edited_text": None,
        "human_notes": "note",
        "reviewer_name": "rev1"
    }]

    export_records_to_excel(records, out_file, include_hitl_columns=True)
    wb = openpyxl.load_workbook(out_file)
    ws = wb.active
    headers = [cell.value for cell in ws[1] if cell.value is not None]

    assert len(headers) == len(set(headers)), f"Duplicate headers found in Excel: {headers}"


def test_reproduce_native_persian_rejected_not_in_accepted(tmp_path):
    """
    BUG: native_fa records with quality_status='rejected' (e.g. human rejected)
    were erroneously included in accepted_persian!
    """
    from persianization.storage import PersianizationStorage
    from persianization.exporter import export_persianization_outputs

    db_path = str(tmp_path / "persian_rejected.db")
    storage = PersianizationStorage(db_path)

    storage.save_record({
        "id": "rec_nat_rejected",
        "raw_text": "متن نامناسب فارسی",
        "origin": "native_fa",
        "translation_status": "not_required",
        "quality_status": "rejected",  # REJECTED!
        "split": "train",
        "group_id": "grp1"
    })

    out_dir = str(tmp_path / "out_export")
    config = load_config()
    export_persianization_outputs(storage, out_dir, "run1", config.__dict__, {})

    import json
    with open(f"{out_dir}/accepted_persian.jsonl") as f:
        accepted_lines = [json.loads(line) for line in f if line.strip()]

    acc_ids = [r["id"] for r in accepted_lines]
    assert "rec_nat_rejected" not in acc_ids, "Rejected native_fa record must NOT be in accepted_persian!"

