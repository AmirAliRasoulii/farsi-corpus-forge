"""
Independent Dual Quality Evaluators (QUALITY_MODEL_1 and QUALITY_MODEL_2).
Executes primary quality control, context-applicability checks, and blind secondary evaluation
for stable 10% random audits and targeted high-risk cases.
"""
import json
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from shared.api_client import AvalAIClient, AuthenticationError
from shared.rate_limiter import BudgetExceededError
from shared.circuit_breaker import CircuitBreakerTripped
from shared.schema_validator import validate_quality_judge_output, SchemaValidationError
from persianization.storage import PersianizationStorage
from persianization.config import PersianizationConfig


def compute_qc_cache_key(
    raw_text: str,
    text_fa: str,
    raw_context: Optional[str],
    context_fa: Optional[str],
    model: str,
    prompt_hash: str,
    policy_hash: str
) -> str:
    """Deterministic cache key incorporating prompt, model, text, context, and policy hash."""
    key_str = f"{raw_text}||{text_fa}||{raw_context or ''}||{context_fa or ''}||{model}||{prompt_hash}||{policy_hash}"
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()


def is_sampled_for_judge_2_random(record_id: str, sample_rate: float) -> bool:
    """Stable hash-based sampling for secondary random audit."""
    if sample_rate <= 0.0:
        return False
    if sample_rate >= 1.0:
        return True
    digest = hashlib.sha256(f"judge2_random_{record_id}".encode("utf-8")).hexdigest()
    val = int(digest[:8], 16) % 10000
    return val < int(sample_rate * 10000)


def is_sampled_for_human_audit(record_id: str, sample_rate: float) -> bool:
    """Stable hash-based sampling for human audit."""
    if sample_rate <= 0.0:
        return False
    if sample_rate >= 1.0:
        return True
    digest = hashlib.sha256(f"human_audit_{record_id}".encode("utf-8")).hexdigest()
    val = int(digest[:8], 16) % 10000
    return val < int(sample_rate * 10000)


class DualQualityJudge:
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
        self.prompt_hash = hashlib.sha256(config.quality_prompt.encode("utf-8")).hexdigest()[:12]
        self.policy_hash = config.policy_hash

    def evaluate_translation(self, *args, **kwargs):
        return self.evaluate(*args, **kwargs)

    def evaluate(
        self,
        record_id: str,
        raw_text_en: str,
        text_fa: str,
        raw_context_en: Optional[str] = None,
        context_fa: Optional[str] = None,
        translator_model: Optional[str] = None,
        used_fallback: bool = False,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Runs complete evaluation:
        1. Judge 1 evaluates translation.
        2. Checks if Judge 2 is triggered (random 10% or targeted high-risk).
        3. If triggered, Judge 2 evaluates blindly.
        4. Resolves consensus or flags critical disagreement.
        """
        # 1. Verify model independence
        all_generator_models = [self.config.primary_model] + self.config.fallback_models
        if translator_model and translator_model.strip() in (self.config.quality_model_1.strip(), self.config.quality_model_2.strip()):
            return {
                "quality_status": "review_required",
                "scores": {},
                "flags": ["independence_violation"],
                "reason": f"INDEPENDENCE VIOLATION: Generator model '{translator_model}' matches quality evaluator.",
                "evaluator_1_model": self.config.quality_model_1,
                "evaluator_2_model": None,
                "disagreement_flag": False
            }

        # 2. Judge 1 Evaluation
        res1 = self._invoke_judge(
            judge_model=self.config.quality_model_1,
            route=self.config.quality_1_route,
            output_mode=self.config.quality_1_output_mode,
            max_tokens=self.config.quality_1_max_tokens,
            token_field=self.config.quality_1_token_field,
            temperature=self.config.quality_1_temperature,
            extra_params=self.config.quality_1_extra_json,
            step_name="quality_judge_1",
            record_id=record_id,
            raw_text_en=raw_text_en,
            text_fa=text_fa,
            raw_context_en=raw_context_en,
            context_fa=context_fa,
            request_id=request_id
        )

        scores1 = res1.get("scores", {})
        flags1 = res1.get("flags", [])
        j1_passed = res1.get("passed", False)
        reason1 = res1.get("reason", "")

        # 3. Determine if Judge 2 is needed
        needs_judge_2 = False
        sampling_type = None

        if self.config.second_judge_targeted_enabled:
            # Check targeted conditions
            has_suspect_flag = any(f in flags1 for f in ("censored_content", "severity_changed", "meaning_changed", "target_changed"))
            is_borderline = any(scores1.get(d) == self.config.quality_accept_threshold for d in scores1)
            
            if used_fallback:
                needs_judge_2 = True
                sampling_type = "targeted_fallback"
            elif has_suspect_flag:
                needs_judge_2 = True
                sampling_type = "targeted_suspected_flag"
            elif is_borderline:
                needs_judge_2 = True
                sampling_type = "targeted_borderline"

        # If not targeted, check stable random sample for initially acceptable candidates
        if not needs_judge_2 and j1_passed:
            if is_sampled_for_judge_2_random(record_id, self.config.second_judge_random_sample_rate):
                needs_judge_2 = True
                sampling_type = "random_sample"

        scores2 = None
        flags2 = None
        reason2 = None
        disagreement = False

        if needs_judge_2:
            res2 = self._invoke_judge(
                judge_model=self.config.quality_model_2,
                route=self.config.quality_2_route,
                output_mode=self.config.quality_2_output_mode,
                max_tokens=self.config.quality_2_max_tokens,
                token_field=self.config.quality_2_token_field,
                temperature=self.config.quality_2_temperature,
                extra_params=self.config.quality_2_extra_json,
                step_name="quality_judge_2",
                record_id=record_id,
                raw_text_en=raw_text_en,
                text_fa=text_fa,
                raw_context_en=raw_context_en,
                context_fa=context_fa,
                request_id=request_id
            )

            scores2 = res2.get("scores", {})
            flags2 = res2.get("flags", [])
            j2_passed = res2.get("passed", False)
            reason2 = res2.get("reason", "")

            # Check critical disagreement
            blocking_flags = set(self.policy.get("blocking_flags", []))
            j1_blocking = any(f in blocking_flags for f in flags1)
            j2_blocking = any(f in blocking_flags for f in flags2)

            if j1_passed != j2_passed or j1_blocking != j2_blocking:
                disagreement = True
                final_quality_status = "review_required"
                reason_combined = f"[Disagreement: J1={'Pass' if j1_passed else 'Fail'}, J2={'Pass' if j2_passed else 'Fail'}] {reason1} | {reason2}"
            elif not j1_passed and not j2_passed:
                final_quality_status = "rejected"
                reason_combined = f"[Both Judges Rejected] {reason1} | {reason2}"
            else:
                # Both passed
                # Check human audit sampling
                if is_sampled_for_human_audit(record_id, self.config.human_audit_sample_rate):
                    final_quality_status = "pending_human_audit"
                    reason_combined = f"[Sampled for Human Audit] {reason1}"
                else:
                    final_quality_status = "accepted"
                    reason_combined = reason1
        else:
            if j1_passed:
                if is_sampled_for_human_audit(record_id, self.config.human_audit_sample_rate):
                    final_quality_status = "pending_human_audit"
                    reason_combined = f"[Sampled for Human Audit] {reason1}"
                else:
                    final_quality_status = "accepted"
                    reason_combined = reason1
            else:
                blocking_flags = set(self.policy.get("blocking_flags", []))
                has_blocking = any(f in blocking_flags for f in flags1)
                final_quality_status = "rejected" if has_blocking else "review_required"
                reason_combined = reason1

        return {
            "quality_status": final_quality_status,
            "scores": scores1,
            "flags": flags1,
            "reason": reason_combined,
            "evaluator_1_model": self.config.quality_model_1,
            "evaluator_2_model": self.config.quality_model_2 if needs_judge_2 else None,
            "quality_scores_2": scores2,
            "quality_flags_2": flags2,
            "second_judge_reason": reason2,
            "second_judge_sampling_type": sampling_type,
            "disagreement_flag": disagreement
        }

    def _invoke_judge(
        self,
        judge_model: str,
        route: str,
        output_mode: str,
        max_tokens: int,
        token_field: str,
        temperature: float,
        extra_params: Dict[str, Any],
        step_name: str,
        record_id: str,
        raw_text_en: str,
        text_fa: str,
        raw_context_en: Optional[str],
        context_fa: Optional[str],
        request_id: Optional[str]
    ) -> Dict[str, Any]:
        """Invokes a quality evaluator model with caching and rubric parsing."""
        cache_key = compute_qc_cache_key(
            raw_text=raw_text_en,
            text_fa=text_fa,
            raw_context=raw_context_en,
            context_fa=context_fa,
            model=judge_model,
            prompt_hash=self.prompt_hash,
            policy_hash=self.policy_hash
        )

        cached = self.storage.get_cache(cache_key)
        if cached:
            return cached

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
                model=judge_model,
                messages=messages,
                api_route=route,
                max_tokens=max_tokens,
                token_field=token_field,
                output_mode=output_mode,
                temperature=temperature,
                extra_params=extra_params
            )

            parsed = res.get("parsed_json")
            raw_comp = res.get("raw_completion", "")

            self.storage.record_attempt(
                record_id=record_id,
                step=step_name,
                model=judge_model,
                usage=res.get("usage", {}),
                latency_sec=res.get("latency_sec", 0.0),
                raw_completion=raw_comp,
                parsed_json=parsed,
                status="success" if parsed else "failed",
                error_message=None if parsed else "Failed to parse QC JSON",
                request_id=request_id
            )

            has_context = bool(raw_context_en and raw_context_en.strip())
            try:
                validated = validate_quality_judge_output(parsed, has_context=has_context, raw_completion=raw_comp)
            except SchemaValidationError as sve:
                self.storage.record_attempt(
                    record_id=record_id,
                    step=step_name,
                    model=judge_model,
                    usage=res.get("usage", {}),
                    latency_sec=res.get("latency_sec", 0.0),
                    raw_completion=raw_comp,
                    parsed_json=parsed,
                    status="failed",
                    error_message=f"Schema validation error: {sve}",
                    request_id=request_id
                )
                return {
                    "passed": False,
                    "scores": {},
                    "flags": ["qc_schema_error"],
                    "reason": f"Model '{judge_model}' output schema validation failed: {sve}"
                }

            scores = validated["scores"]
            flags = list(validated["flags"])
            preservation = validated["preservation_checks"]

            # Any failed preservation check adds a changed flag AND blocks acceptance
            preservation_all_true = True
            for check_key, val in preservation.items():
                if val is False:
                    preservation_all_true = False
                    flag_name = check_key.replace("_preserved", "_changed")
                    if flag_name not in flags:
                        flags.append(flag_name)

            min_threshold = self.config.quality_accept_threshold
            blocking_flags = set(self.policy.get("blocking_flags", []))
            required_dimensions = self.policy.get("required_dimensions", [
                "fluency", "naturalness", "register_match", "cultural_fit", "semantic_fidelity", "severity_fidelity"
            ])

            has_blocking_flag = any(f in blocking_flags for f in flags)
            all_required_pass = all(scores.get(d, 0) >= min_threshold for d in required_dimensions)

            # When context exists, context_fidelity score MUST be >= min_threshold
            if has_context:
                ctx_score = scores.get("context_fidelity")
                context_pass = (ctx_score is not None and ctx_score >= min_threshold)
            else:
                context_pass = True

            passed = all_required_pass and context_pass and preservation_all_true and not has_blocking_flag

            result_data = {
                "passed": passed,
                "scores": scores,
                "flags": flags,
                "reason": validated.get("reason", "")
            }
            self.storage.set_cache(cache_key, result_data)
            return result_data

        except (AuthenticationError, BudgetExceededError, CircuitBreakerTripped):
            raise
        except Exception as e:
            self.storage.record_attempt(
                record_id=record_id,
                step=step_name,
                model=judge_model,
                usage={},
                latency_sec=0.0,
                raw_completion="",
                parsed_json=None,
                status="failed",
                error_message=str(e),
                request_id=request_id
            )
            return {
                "passed": False,
                "scores": {},
                "flags": ["qc_exception"],
                "reason": str(e)
            }


# Backwards compatibility alias
QualityJudge = DualQualityJudge

