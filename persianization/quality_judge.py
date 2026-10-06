"""
Independent Quality Control (QC) judge for Persian translations.
Verifies model independence, evaluates 1-5 dimensions, checks preservation flags,
and executes deterministic human audit sampling.
"""
import json
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from shared.api_client import AvalAIClient
from persianization.storage import PersianizationStorage
from persianization.config import PersianizationConfig


def is_sampled_for_audit(record_id: str, sample_rate: float) -> bool:
    """
    Deterministic, stable sampling based on record ID hash.
    Ensures identical sampling across reruns and workers.
    """
    if sample_rate <= 0.0:
        return False
    if sample_rate >= 1.0:
        return True
    digest = hashlib.sha256(record_id.encode('utf-8')).hexdigest()
    # Use first 8 hex characters as int modulo 10000
    val = int(digest[:8], 16) % 10000
    return val < int(sample_rate * 10000)


class QualityJudge:
    def __init__(
        self,
        config: PersianizationConfig,
        api_client: AvalAIClient,
        storage: PersianizationStorage
    ):
        self.config = config
        self.client = api_client
        self.storage = storage
        self.policy = config.review_policy

    def evaluate_translation(
        self,
        record_id: str,
        raw_text_en: str,
        text_fa: str,
        raw_context_en: Optional[str] = None,
        context_fa: Optional[str] = None,
        translator_model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Runs independent quality evaluation.
        Enforces model independence rule strictly.
        """
        # 1. Verify model independence
        if translator_model and translator_model.strip() == self.config.quality_model.strip():
            return {
                "quality_status": "review_required",
                "scores": {},
                "flags": ["independence_violation"],
                "reason": (
                    f"INDEPENDENCE VIOLATION: Quality model '{self.config.quality_model}' is identical to "
                    f"translator model '{translator_model}'. Independent evaluation cannot be performed."
                ),
                "evaluator_model": self.config.quality_model
            }

        # Build prompt
        prompt_content = f"English original:\n{raw_text_en}\n\nPersian translation candidate:\n{text_fa}"
        if raw_context_en:
            prompt_content += f"\n\nEnglish context:\n{raw_context_en}"
        if context_fa:
            prompt_content += f"\n\nPersian context candidate:\n{context_fa}"

        messages = [
            {"role": "system", "content": self.config.quality_prompt},
            {"role": "user", "content": prompt_content}
        ]

        try:
            res = self.client.invoke(
                model=self.config.quality_model,
                messages=messages,
                api_route=self.config.quality_route,
                max_tokens=self.config.quality_max_tokens,
                token_field=self.config.quality_token_field,
                output_mode=self.config.quality_output_mode,
                temperature=self.config.quality_temperature,
                extra_params=self.config.quality_extra_json
            )

            parsed = res.get("parsed_json")
            raw_comp = res.get("raw_completion", "")

            # Log attempt
            self.storage.record_attempt(
                record_id=record_id,
                step="quality_evaluation",
                model=self.config.quality_model,
                usage=res.get("usage", {}),
                latency_sec=res.get("latency_sec", 0.0),
                raw_completion=raw_comp,
                parsed_json=parsed,
                status="success" if parsed else "failed",
                error_message=None if parsed else "Failed to parse QC evaluation JSON"
            )

            if not parsed:
                return {
                    "quality_status": "review_required",
                    "scores": {},
                    "flags": ["qc_schema_error"],
                    "reason": "Quality model failed to return valid JSON schema.",
                    "evaluator_model": self.config.quality_model
                }

            return self._apply_acceptance_policy(record_id, parsed)

        except Exception as e:
            self.storage.record_attempt(
                record_id=record_id,
                step="quality_evaluation",
                model=self.config.quality_model,
                usage={},
                latency_sec=0.0,
                raw_completion="",
                parsed_json=None,
                status="failed",
                error_message=str(e)
            )
            return {
                "quality_status": "review_required",
                "scores": {},
                "flags": ["qc_execution_error"],
                "reason": f"Quality evaluation error: {str(e)}",
                "evaluator_model": self.config.quality_model
            }

    def _apply_acceptance_policy(self, record_id: str, parsed: Dict[str, Any]) -> Dict[str, Any]:
        """Applies policy thresholds and human audit sampling."""
        min_threshold = self.config.quality_accept_threshold
        blocking_flags = set(self.policy.get("blocking_flags", []))
        required_dimensions = self.policy.get("required_dimensions", [
            "fluency", "naturalness", "register_match", "cultural_fit", "semantic_fidelity", "severity_fidelity"
        ])

        scores = {}
        for dim in required_dimensions:
            val = parsed.get(dim)
            try:
                scores[dim] = int(val) if val is not None else 1
            except Exception:
                scores[dim] = 1

        raw_flags = parsed.get("flags") or []
        flags = [str(f).strip() for f in raw_flags if f]

        # Binary checks
        preservation_checks = {
            "target_preserved": parsed.get("target_preserved", True),
            "stance_preserved": parsed.get("stance_preserved", True),
            "negation_preserved": parsed.get("negation_preserved", True),
            "quotation_preserved": parsed.get("quotation_preserved", True),
            "ambiguity_preserved": parsed.get("ambiguity_preserved", True),
        }

        # Check binary failures and add corresponding flags
        for k, v in preservation_checks.items():
            if v is False:
                flag_name = k.replace("_preserved", "_changed")
                if flag_name not in flags:
                    flags.append(flag_name)

        has_blocking_flag = any(f in blocking_flags for f in flags)
        all_dimensions_pass = all(scores.get(d, 0) >= min_threshold for d in required_dimensions)

        reason = parsed.get("reason", "")

        if all_dimensions_pass and not has_blocking_flag:
            # Candidate passes automated criteria!
            # Check if sampled for human audit
            if is_sampled_for_audit(record_id, self.config.human_audit_sample_rate):
                status = "pending_human_audit"
                reason_full = f"[Sampled for Human Audit] {reason}"
            else:
                status = "accepted"
                reason_full = reason
        else:
            status = "review_required"
            violations = []
            if not all_dimensions_pass:
                low_dims = [f"{d}={scores.get(d)}" for d in required_dimensions if scores.get(d, 0) < min_threshold]
                violations.append(f"Low scores: {', '.join(low_dims)}")
            if has_blocking_flag:
                active_blocking = [f for f in flags if f in blocking_flags]
                violations.append(f"Blocking flags: {', '.join(active_blocking)}")
            reason_full = f"{reason} ({'; '.join(violations)})".strip()

        return {
            "quality_status": status,
            "scores": scores,
            "flags": flags,
            "preservation_checks": preservation_checks,
            "reason": reason_full,
            "evaluator_model": self.config.quality_model
        }
