"""
Language routing for target text and context.
Directly routes native Persian without calling translation models,
and routes English or mixed text appropriately.
"""
from typing import Dict, Any, Tuple
from shared.language_detector import detect_language


def route_record_languages(
    text: str,
    context: str = None,
    declared_language: str = None
) -> Dict[str, Any]:
    """
    Evaluates text and context independently.
    
    Returns a routing decision:
      - text_lang_info: dict
      - context_lang_info: dict
      - origin: 'native_fa' | 'translated_en_to_fa' | 'fingilish' | 'uncertain'
      - requires_text_translation: bool
      - requires_context_translation: bool
      - routing_status: 'ready' | 'needs_review'
      - reason: str
    """
    text_info = detect_language(text, declared_language=declared_language)
    context_info = detect_language(context) if context else None

    text_lang = text_info["lang"]
    requires_text_translation = False
    requires_context_translation = False
    routing_status = "ready"
    reason = text_info["reason"]

    # Evaluate target text
    if text_info.get("is_uncertain") or "language_script_conflict" in text_info.get("flags", []):
        origin = text_info.get("origin_status", "uncertain")
        requires_text_translation = False
        routing_status = "needs_review"
    elif text_lang == "fa":
        origin = "native_fa"
        requires_text_translation = False
    elif text_lang == "en":
        origin = "translated_en_to_fa"
        requires_text_translation = True
    elif text_lang == "fingilish":
        origin = "fingilish"
        requires_text_translation = False  # Do not guess-translate without explicit instruction
        routing_status = "needs_review"
    elif text_lang == "mixed":
        # Mixed script
        if "persian_dominant" in text_info["flags"]:
            origin = "native_fa"
            requires_text_translation = False
        else:
            origin = "uncertain"
            requires_text_translation = False
            routing_status = "needs_review"
    else:
        origin = "uncertain"
        requires_text_translation = False
        routing_status = "needs_review"

    # Evaluate context text independently!
    # A Persian text with English context should NOT retranslate Persian text.
    if context_info:
        if context_info["lang"] == "en" and requires_text_translation:
            # Both need translation
            requires_context_translation = True
        elif context_info["lang"] == "en" and not requires_text_translation:
            # Text is native Persian, but context is English
            # Mark context as needing translation without touching native Persian text
            requires_context_translation = True
        elif context_info["lang"] == "fa":
            requires_context_translation = False

    return {
        "text_lang_info": text_info,
        "context_lang_info": context_info,
        "origin": origin,
        "requires_text_translation": requires_text_translation,
        "requires_context_translation": requires_context_translation,
        "routing_status": routing_status,
        "reason": reason
    }
