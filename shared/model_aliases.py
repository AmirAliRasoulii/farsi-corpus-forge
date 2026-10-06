"""
Canonical model alias normalization and independence verification.
Prevents dated aliases or vendor synonyms from falsely appearing independent.
"""
from typing import Dict, List, Optional

CANONICAL_MODEL_ALIASES: Dict[str, str] = {
    # OpenAI snapshots
    "gpt-4o-mini-2024-07-18": "gpt-4o-mini",
    "gpt-4o-2024-08-06": "gpt-4o",
    "gpt-4o-2024-05-13": "gpt-4o",
    "gpt-4-turbo-2024-04-09": "gpt-4-turbo",
    "gpt-3.5-turbo-0125": "gpt-3.5-turbo",
    
    # Anthropic snapshots
    "claude-3-5-haiku-20241022": "claude-haiku-4-5",
    "claude-3-5-sonnet-20241022": "claude-3-5-sonnet",
    "claude-3-5-sonnet-20240620": "claude-3-5-sonnet",
    "claude-3-opus-20240229": "claude-3-opus",
    
    # Google snapshots
    "gemini-2.0-flash": "gemini-2.5-flash",
    "gemini-2.0-flash-exp": "gemini-2.5-flash",
    "gemini-1.5-pro-latest": "gemini-1.5-pro",
    "gemini-1.5-flash-latest": "gemini-1.5-flash",
}


def canonicalize_model_id(model_id: Optional[str]) -> str:
    """
    Normalizes a model ID by stripping whitespace, lowercasing,
    and mapping known dated snapshots / vendor aliases to canonical base IDs.
    
    NOTE: Different canonical IDs do NOT prove statistical independence
    across model families (e.g., distillation or shared pretraining),
    but identical canonical IDs guarantee lack of independence.
    """
    if not model_id:
        return ""
    cleaned = model_id.strip().lower()
    return CANONICAL_MODEL_ALIASES.get(cleaned, cleaned)
