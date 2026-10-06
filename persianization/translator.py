"""
Translator engine handling primary model execution, refusal detection,
and ordered fallback models using pristine raw text and context.
Includes cache invalidation upon prompt/policy change and standalone context translation.
"""
import re
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from shared.api_client import AvalAIClient, ModelRefusalError, extract_json_from_completion, AuthenticationError
from shared.rate_limiter import BudgetExceededError
from shared.circuit_breaker import CircuitBreakerTripped
from shared.schema_validator import validate_translator_output, SchemaValidationError
from persianization.storage import PersianizationStorage
from persianization.config import PersianizationConfig


# English refusal indicator patterns (meta-refusals from model, distinct from translated content)
MODEL_REFUSAL_REASONS = [
    re.compile(r'\b(as an ai|i cannot fulfill|against (our|my) (safety|content) polic|i am unable to assist)\b', re.IGNORECASE),
    re.compile(r'\b(harmful|offensive language|hate speech policy)\b', re.IGNORECASE)
]

# Patterns in English original indicating genuine "cannot" sentences
GENUINE_CANNOT_ORIGINAL = re.compile(r"\b(i cannot|i can't|can not|we cannot|we can't|unable to|impossible)\b", re.IGNORECASE)


def compute_translator_cache_key(
    text: str,
    context: Optional[str],
    model: str,
    prompt_hash: str,
    policy_hash: str,
    schema_version: str = "v2"
) -> str:
    raw = f"{text}||{context or ''}||{model}||{prompt_hash}||{policy_hash}||{schema_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TranslationEngine:
    def __init__(
        self,
        config: PersianizationConfig,
        api_client: AvalAIClient,
        storage: PersianizationStorage
    ):
        self.config = config
        self.client = api_client
        self.storage = storage
        self.prompt_hash = hashlib.sha256(config.translator_prompt.encode("utf-8")).hexdigest()[:12]
        self.policy_hash = config.policy_hash

    def translate_record(
        self,
        record_id: str,
        raw_text: str,
        raw_context: Optional[str] = None,
        request_id: Optional[str] = None,
        start_model_idx: int = 0
    ) -> Dict[str, Any]:
        """
        Translates a record using primary model and ordered fallbacks.
        Always sends raw original text to fallback models (no daisy-chaining).
        """
        candidate_models = [self.config.primary_model] + self.config.fallback_models
        ordered_models = []
        for m in candidate_models:
            if m and m not in ordered_models:
                ordered_models.append(m)

        # Slice models starting from requested index
        available_models = ordered_models[start_model_idx:]

        last_error = None
        for idx_offset, model in enumerate(available_models):
            current_model_idx = start_model_idx + idx_offset
            cache_key = compute_translator_cache_key(
                text=raw_text,
                context=raw_context,
                model=model,
                prompt_hash=self.prompt_hash,
                policy_hash=self.policy_hash
            )
            cached_resp = self.storage.get_cache(cache_key)
            if cached_resp:
                cached_resp["model_idx"] = current_model_idx
                cached_resp["used_fallback"] = (current_model_idx > 0)
                return cached_resp

            user_content = f"English text to translate:\n{raw_text}"
            if raw_context:
                user_content += f"\n\nContext:\n{raw_context}"

            messages = [
                {"role": "system", "content": self.config.translator_prompt},
                {"role": "user", "content": user_content}
            ]

            try:
                res = self.client.invoke(
                    model=model,
                    messages=messages,
                    api_route=self.config.translator_route,
                    max_tokens=self.config.translator_max_tokens,
                    token_field=self.config.translator_token_field,
                    output_mode=self.config.translator_output_mode,
                    temperature=self.config.translator_temperature,
                    extra_params=self.config.translator_extra_json
                )

                parsed = res.get("parsed_json")
                raw_comp = res.get("raw_completion", "")

                # Validate strict schema first
                try:
                    valid_parsed = validate_translator_output(parsed, raw_comp)
                    status_eval, error_msg = self._evaluate_translation_response(
                        raw_text=raw_text,
                        parsed=valid_parsed,
                        raw_completion=raw_comp
                    )
                    clean_text_fa = valid_parsed.get("text_fa")
                    clean_ctx_fa = valid_parsed.get("context_fa")
                    clean_reason = valid_parsed.get("reason", "")
                except SchemaValidationError as sve:
                    status_eval = "schema_error"
                    error_msg = str(sve)
                    clean_text_fa = None
                    clean_ctx_fa = None
                    clean_reason = f"Schema validation error: {sve}"

                self.storage.record_attempt(
                    record_id=record_id,
                    request_id=request_id,
                    step="translation",
                    model=model,
                    usage=res.get("usage", {}),
                    latency_sec=res.get("latency_sec", 0.0),
                    raw_completion=raw_comp,
                    parsed_json=parsed,
                    status=status_eval,
                    error_message=error_msg
                )

                if status_eval in ("translated", "uncertain") and clean_text_fa:
                    result_data = {
                        "translation_status": status_eval,
                        "text_fa": clean_text_fa,
                        "context_fa": clean_ctx_fa,
                        "reason": clean_reason,
                        "selected_model": model,
                        "model_idx": current_model_idx,
                        "used_fallback": (current_model_idx > 0),
                        "error_message": None
                    }
                    self.storage.set_cache(cache_key, result_data)
                    return result_data
                else:
                    # Model refused or failed schema; continue to next fallback
                    last_error = error_msg or f"Model '{model}' returned status '{status_eval}'"
                    continue

            except (AuthenticationError, BudgetExceededError, CircuitBreakerTripped):
                # Critical control exceptions must never be swallowed or continue to next fallback!
                raise
            except Exception as e:
                last_error = str(e)
                self.storage.record_attempt(
                    record_id=record_id,
                    request_id=request_id,
                    step="translation",
                    model=model,
                    usage={},
                    latency_sec=0.0,
                    raw_completion="",
                    parsed_json=None,
                    status="failed",
                    error_message=str(e)
                )
                continue


        # All fallback models exhausted
        return {
            "translation_status": "unresolved",
            "text_fa": None,
            "context_fa": None,
            "reason": f"All translator models exhausted. Last error: {last_error}",
            "selected_model": None,
            "model_idx": len(ordered_models),
            "used_fallback": True,
            "error_message": last_error
        }

    def translate_context_only(
        self,
        record_id: str,
        context_en: str,
        request_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Translates English context when target text is Native Persian.
        Never touches or re-translates the Native Persian target text.
        """
        if not context_en or not context_en.strip():
            return None

        tr_res = self.translate_record(
            record_id=f"{record_id}_ctx",
            raw_text=context_en,
            raw_context=None,
            request_id=request_id
        )
        return tr_res.get("text_fa")

    def _evaluate_translation_response(
        self,
        raw_text: str,
        parsed: Optional[Dict[str, Any]],
        raw_completion: str
    ) -> Tuple[str, Optional[str]]:
        """
        Inspects model completion for refusal, unable, schema validity, or genuine 'cannot'.
        """
        if not parsed:
            return "failed", "JSON parsing failed or empty response"

        status = parsed.get("status", "").lower().strip()
        text_fa = parsed.get("text_fa")
        reason = parsed.get("reason", "")

        # 1. Explicit model unable / refusal
        if status == "unable" or not text_fa:
            return "unable", f"Model indicated unable to translate: {reason}"

        # 2. Check if refusal text exists in reason or raw completion
        for p in MODEL_REFUSAL_REASONS:
            if p.search(reason) or p.search(raw_completion):
                if not GENUINE_CANNOT_ORIGINAL.search(raw_text):
                    return "refused", f"Explicit safety policy refusal detected: {reason}"

        # 3. Check for 'نمی‌توانم' in Persian text
        if ("نمی‌توانم" in str(text_fa) or "نمیتوانم" in str(text_fa) or "نمیتونم" in str(text_fa)):
            if not GENUINE_CANNOT_ORIGINAL.search(raw_text):
                if len(str(text_fa).split()) < 12 and ("ترجمه" in str(text_fa) or "محتوا" in str(text_fa)):
                    return "refused", "Model output Persian refusal sentence instead of translating"

        if status == "uncertain":
            return "uncertain", None

        return "translated", None
