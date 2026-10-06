"""
Unit tests for language detection and routing logic.
"""
from shared.language_detector import detect_language
from persianization.router import route_record_languages


def test_native_persian_direct_entry():
    text = "این یک پیام فارسی کاملاً سالم است و نیاز به ترجمه ندارد."
    res = route_record_languages(text)
    assert res["origin"] == "native_fa"
    assert res["requires_text_translation"] is False
    assert res["routing_status"] == "ready"


def test_english_translation_routing():
    text = "This is a standard English sentence that needs translation."
    res = route_record_languages(text)
    assert res["origin"] == "translated_en_to_fa"
    assert res["requires_text_translation"] is True
    assert res["routing_status"] == "ready"


def test_text_context_language_separation():
    """Persian target text with English context must NOT cause re-translation of Persian text."""
    target_text = "من با این تصمیم کاملاً موافقم."
    context_text = "Discussion regarding the company's annual budget."
    res = route_record_languages(target_text, context=context_text)

    assert res["origin"] == "native_fa"
    assert res["requires_text_translation"] is False  # Target Persian text must NOT be translated
    assert res["requires_context_translation"] is True  # Context needs translation


def test_fingilish_not_treated_as_native_fa():
    text = "salam dadash halet chetore emrooz nemiam sar kar"
    res = route_record_languages(text)
    assert res["origin"] == "fingilish"
    assert res["requires_text_translation"] is False  # Must not guess-translate without review
    assert res["routing_status"] == "needs_review"


def test_persian_with_english_loanwords_stays_persian():
    """English loanwords like 'Instagram' or 'Online' should not make Persian sentence English."""
    text = "من دیروز در Instagram یک ویدئوی آموزشی آنلاین دیدم."
    res = route_record_languages(text)
    assert res["origin"] == "native_fa"
    assert res["requires_text_translation"] is False
