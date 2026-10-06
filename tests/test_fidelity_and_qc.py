"""
Unit tests for quality evaluation, independence checks, and offense separation.
"""
from shared.api_client import AvalAIClient
from persianization.config import load_config
from persianization.storage import PersianizationStorage
from persianization.quality_judge import QualityJudge
from mock_demo.mock_llm import mock_llm_handler


def test_quality_evaluator_catches_censorship(tmp_path):
    db_path = str(tmp_path / "test_qc.db")
    storage = PersianizationStorage(db_path)
    config = load_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    judge = QualityJudge(config, client, storage)

    # Simulate evaluation of censored candidate
    res = judge.evaluate_translation(
        record_id="rec_test",
        raw_text_en="Get out of here, you absolute idiot!",
        text_fa="لطفاً از اینجا تشریف ببرید فرد کم‌هوش [سانسور شده]",
        translator_model="gpt-4o-mini"
    )

    assert res["quality_status"] in ("review_required", "rejected")
    assert "censored_content" in res["flags"] or "severity_changed" in res["flags"]


def test_independence_violation_check(tmp_path):
    db_path = str(tmp_path / "test_qc.db")
    storage = PersianizationStorage(db_path)
    config = load_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    judge = QualityJudge(config, client, storage)

    # When translator_model is identical to quality_model
    res = judge.evaluate_translation(
        record_id="rec_indep",
        raw_text_en="Some text",
        text_fa="متن ترجمه",
        translator_model=config.quality_model  # IDENTICAL MODEL
    )

    assert "independence_violation" in res["flags"]
    assert res["quality_status"] == "review_required"


def test_native_fa_and_source_label_not_auto_label0(tmp_path):
    """
    Direct entry of native Persian and source_label 0 does NOT auto-certify final offense label.
    Project A must maintain offense_label = None and annotation_status = 'not_annotated'.
    """
    db_path = str(tmp_path / "test_state.db")
    storage = PersianizationStorage(db_path)

    rec_data = {
        "id": "rec_nat",
        "text": "یک متن کاملاً بومی با منبع تمیز",
        "context": None,
        "language": "fa",
        "origin": "native_fa",
        "translation_status": "not_required",
        "quality_status": "not_required",
        "offense_label": None,
        "annotation_status": "not_annotated",
        "final_persian_text": "یک متن کاملاً بومی با منبع تمیز",
        "final_persian_context": None,
        "selected_model": None,
        "quality_scores": None,
        "quality_flags": [],
        "reason": "Direct Persian entry",
        "source": "corpus",
        "source_label": 0,
        "parent_id": None,
        "group_id": "rec_nat",
        "split": "train",
        "metadata": {}
    }
    storage.save_record(rec_data)

    saved = storage.fetch_all_records()[0]
    assert saved["offense_label"] is None
    assert saved["annotation_status"] == "not_annotated"
