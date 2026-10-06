"""
Unit tests for model refusals, ordered fallbacks, and 'cannot' handling.
"""
from shared.api_client import AvalAIClient
from persianization.config import load_config
from persianization.storage import PersianizationStorage
from persianization.translator import TranslationEngine
from mock_demo.mock_llm import mock_llm_handler


def test_cannot_phrase_in_genuine_translation_not_refusal(tmp_path):
    """Original sentence containing 'cannot' should not be falsely treated as model refusal."""
    db_path = str(tmp_path / "test_tr.db")
    storage = PersianizationStorage(db_path)
    config = load_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    engine = TranslationEngine(config, client, storage)

    res = engine.translate_record(
        record_id="rec_cannot",
        raw_text="I really cannot understand why the system failed so badly."
    )

    assert res["translation_status"] == "translated"
    assert "نمی‌توانم" in res["text_fa"]


def test_fallback_called_when_primary_refuses(tmp_path):
    """When primary model refuses, ordered fallback is called with raw original text."""
    db_path = str(tmp_path / "test_fallback.db")
    storage = PersianizationStorage(db_path)
    config = load_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    engine = TranslationEngine(config, client, storage)

    res = engine.translate_record(
        record_id="rec_fallback_test",
        raw_text="Get out of here, you absolute idiot! [FORCE_FALLBACK_ON_PRIMARY]"
    )

    # Primary gpt-4o-mini refused, but fallback succeeded
    assert res["translation_status"] == "translated"
    assert res["selected_model"] != "gpt-4o-mini"
    assert res["selected_model"] in config.fallback_models


def test_all_fallbacks_failing_produces_unresolved(tmp_path):
    """When all models refuse or fail, result must be marked unresolved."""
    db_path = str(tmp_path / "test_fail_all.db")
    storage = PersianizationStorage(db_path)
    config = load_config()

    client = AvalAIClient(
        api_key="mock_key",
        mock_handler=mock_llm_handler
    )
    engine = TranslationEngine(config, client, storage)

    res = engine.translate_record(
        record_id="rec_all_refuse",
        raw_text="Some offensive prompt [SIMULATE_REFUSAL]"
    )

    assert res["translation_status"] == "unresolved"
    assert res["text_fa"] is None
