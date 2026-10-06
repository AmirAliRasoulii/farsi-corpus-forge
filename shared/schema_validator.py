"""
Strict Model Output Schema Validator.
Ensures JSON responses conform precisely to contract types and bounds.
Zero optimistic fallbacks: invalid outputs are rejected, logged, and never converted to passing votes.
"""
from typing import Any, Dict, List, Optional


class SchemaValidationError(Exception):
    """Raised when an LLM response fails strict schema validation."""
    def __init__(self, message: str, raw_completion: str = ""):
        super().__init__(message)
        self.raw_completion = raw_completion


def validate_translator_output(parsed: Any, raw_completion: str = "") -> Dict[str, Any]:
    """
    Validates translator model output:
      - Root must be a dict
      - status in ('translated', 'unable', 'refused')
      - text_fa: non-empty string when status == 'translated'; None when unable/refused
      - context_fa: optional string or None
      - reason: string
    """
    if not isinstance(parsed, dict):
        raise SchemaValidationError(
            f"Translator output root must be a JSON object, got {type(parsed).__name__}",
            raw_completion
        )

    status = parsed.get("status")
    if status not in ("translated", "unable", "refused"):
        raise SchemaValidationError(
            f"Translator 'status' must be one of ('translated', 'unable', 'refused'), got '{status}'",
            raw_completion
        )

    text_fa = parsed.get("text_fa")
    if status == "translated":
        if not isinstance(text_fa, str) or not text_fa.strip():
            raise SchemaValidationError(
                "Translator 'text_fa' must be a non-empty string when status is 'translated'",
                raw_completion
            )
    else:
        if text_fa is not None and not isinstance(text_fa, str):
            raise SchemaValidationError(
                f"Translator 'text_fa' must be null or string when status is '{status}', got {type(text_fa).__name__}",
                raw_completion
            )

    context_fa = parsed.get("context_fa")
    if context_fa is not None and not isinstance(context_fa, str):
        raise SchemaValidationError(
            f"Translator 'context_fa' must be null or string, got {type(context_fa).__name__}",
            raw_completion
        )

    reason = parsed.get("reason", "")
    if not isinstance(reason, str):
        reason = str(reason)

    return {
        "status": status,
        "text_fa": text_fa.strip() if isinstance(text_fa, str) else None,
        "context_fa": context_fa.strip() if isinstance(context_fa, str) else None,
        "reason": reason.strip()
    }


def validate_quality_judge_output(
    parsed: Any,
    raw_completion: str = "",
    required_dimensions: Optional[List[str]] = None,
    has_context: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Validates quality judge output:
      - Root must be a dict
      - Each required dimension score must be a strict integer in range [1, 5]
      - context_fidelity: dict with 'applicable' (bool) and 'score' (int 1..5 or None)
      - Binary preservation checks must be strict booleans (not None, not str)
      - flags: list of strings
      - reason: string
    """
    if not isinstance(parsed, dict):
        raise SchemaValidationError(
            f"Quality judge output root must be a JSON object, got {type(parsed).__name__}",
            raw_completion
        )

    req_dims = required_dimensions or [
        "fluency", "naturalness", "register_match", "cultural_fit", "semantic_fidelity", "severity_fidelity"
    ]

    scores: Dict[str, Any] = {}
    for dim in req_dims:
        if dim not in parsed:
            raise SchemaValidationError(
                f"Quality judge output missing required dimension '{dim}'",
                raw_completion
            )
        val = parsed[dim]
        # In Python, bool is a subclass of int (isinstance(True, int) is True), so check not bool
        if isinstance(val, bool) or not isinstance(val, int) or val < 1 or val > 5:
            raise SchemaValidationError(
                f"Quality judge score for '{dim}' must be an integer between 1 and 5, got {repr(val)} ({type(val).__name__})",
                raw_completion
            )
        scores[dim] = val

    # Context fidelity validation
    ctx_val = parsed.get("context_fidelity")
    if isinstance(ctx_val, dict):
        app = ctx_val.get("applicable")
        if not isinstance(app, bool):
            raise SchemaValidationError(
                f"context_fidelity.applicable must be boolean, got {repr(app)}",
                raw_completion
            )
        sc = ctx_val.get("score")
        if app:
            if isinstance(sc, bool) or not isinstance(sc, int) or sc < 1 or sc > 5:
                raise SchemaValidationError(
                    f"context_fidelity.score must be integer 1..5 when applicable=True, got {repr(sc)}",
                    raw_completion
                )
            if has_context is False:
                raise SchemaValidationError(
                    "No context was present in raw input, but context_fidelity.applicable was True",
                    raw_completion
                )
            scores["context_fidelity"] = sc
        else:
            if sc is not None:
                raise SchemaValidationError(
                    f"context_fidelity.score must be null when applicable=False, got {repr(sc)}",
                    raw_completion
                )
            if has_context is True:
                raise SchemaValidationError(
                    "Context was present in raw input, but context_fidelity.applicable was False",
                    raw_completion
                )
            scores["context_fidelity"] = None
    elif ctx_val is not None:
        if isinstance(ctx_val, bool) or not isinstance(ctx_val, int) or ctx_val < 1 or ctx_val > 5:
            raise SchemaValidationError(
                f"context_fidelity must be dict or int 1..5, got {repr(ctx_val)}",
                raw_completion
            )
        if has_context is False:
            scores["context_fidelity"] = None
        else:
            scores["context_fidelity"] = ctx_val
    else:
        if has_context is True:
            raise SchemaValidationError(
                "Context was present in raw input, but context_fidelity was missing",
                raw_completion
            )
        scores["context_fidelity"] = None

    # Binary checks validation
    preservation_checks = {}
    for p_key in ("target_preserved", "stance_preserved", "negation_preserved", "quotation_preserved", "ambiguity_preserved"):
        if p_key in parsed:
            val = parsed[p_key]
            if not isinstance(val, bool):
                raise SchemaValidationError(
                    f"Preservation check '{p_key}' must be boolean True or False, got {repr(val)} ({type(val).__name__})",
                    raw_completion
                )
            preservation_checks[p_key] = val
        else:
            raise SchemaValidationError(
                f"Missing required preservation check '{p_key}'",
                raw_completion
            )

    flags_raw = parsed.get("flags", [])
    if not isinstance(flags_raw, list):
        raise SchemaValidationError(
            f"Quality judge 'flags' must be a list of strings, got {type(flags_raw).__name__}",
            raw_completion
        )
    flags = [str(f).strip() for f in flags_raw if f]

    reason = parsed.get("reason", "")
    if not isinstance(reason, str):
        reason = str(reason)

    return {
        "scores": scores,
        "preservation_checks": preservation_checks,
        "flags": flags,
        "reason": reason.strip()
    }


def validate_offense_judge_output(parsed: Any, raw_completion: str = "") -> Dict[str, Any]:
    """
    Validates 4-judge panel offense evaluation:
      - Root must be a dict
      - label: strict int 0 or 1 (strictly rejecting floats, booleans, strings, nulls)
      - confidence: strict float/int in [0.0, 1.0] (rejecting values > 1.0 or < 0.0)
      - reason: string
      - flags: list of strings
    """
    if not isinstance(parsed, dict):
        raise SchemaValidationError(
            f"Offense judge output root must be a JSON object, got {type(parsed).__name__}",
            raw_completion
        )

    if "label" not in parsed:
        raise SchemaValidationError(
            "Offense judge output missing required field 'label'",
            raw_completion
        )

    lbl = parsed["label"]
    # Reject boolean (since bool is subclass of int) and reject non-int
    if isinstance(lbl, bool) or not isinstance(lbl, int) or lbl not in (0, 1):
        raise SchemaValidationError(
            f"Offense judge 'label' must be strict integer 0 or 1, got {repr(lbl)} ({type(lbl).__name__})",
            raw_completion
        )

    # Confidence validation: bounded in [0.0, 1.0]
    conf = parsed.get("confidence")
    if conf is not None:
        if isinstance(conf, bool) or not isinstance(conf, (int, float)):
            raise SchemaValidationError(
                f"Offense judge 'confidence' must be float in range [0.0, 1.0], got {repr(conf)} ({type(conf).__name__})",
                raw_completion
            )
        conf_float = float(conf)
        if conf_float < 0.0 or conf_float > 1.0:
            raise SchemaValidationError(
                f"Offense judge 'confidence' must be in range [0.0, 1.0], got {conf_float}",
                raw_completion
            )
        valid_conf: Optional[float] = conf_float
    else:
        valid_conf = None

    flags_raw = parsed.get("flags", [])
    if not isinstance(flags_raw, list):
        flags = []
    else:
        flags = [str(f).strip() for f in flags_raw if f]

    reason = parsed.get("reason", "")
    if not isinstance(reason, str):
        reason = str(reason)

    return {
        "label": lbl,
        "confidence": valid_conf,
        "flags": flags,
        "reason": reason.strip()
    }


def validate_generator_output(parsed: Any, raw_completion: str = "") -> Dict[str, Any]:
    """
    Validates white generation candidate output:
      - Root must be a dict
      - status in ('generated', 'unable', 'refused')
      - candidate_text: non-empty string when status == 'generated'
      - candidate_context: string or None
      - reason: string
    """
    if not isinstance(parsed, dict):
        raise SchemaValidationError(
            f"Candidate generator output root must be a JSON object, got {type(parsed).__name__}",
            raw_completion
        )

    status = parsed.get("status")
    if status not in ("generated", "unable", "refused"):
        raise SchemaValidationError(
            f"Generator 'status' must be one of ('generated', 'unable', 'refused'), got '{status}'",
            raw_completion
        )

    cand_text = parsed.get("candidate_text")
    if status == "generated":
        if not isinstance(cand_text, str) or not cand_text.strip():
            raise SchemaValidationError(
                "Generator 'candidate_text' must be a non-empty string when status is 'generated'",
                raw_completion
            )
    else:
        cand_text = None

    cand_ctx = parsed.get("candidate_context")
    if cand_ctx is not None and not isinstance(cand_ctx, str):
        cand_ctx = None

    reason = parsed.get("reason", "")
    if not isinstance(reason, str):
        reason = str(reason)

    return {
        "status": status,
        "candidate_text": cand_text.strip() if cand_text else None,
        "candidate_context": cand_ctx.strip() if cand_ctx else None,
        "reason": reason.strip()
    }
