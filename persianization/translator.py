"""
Translator engine handling primary model execution, refusal detection,
and ordered fallback models using pristine raw text.
"""
import re
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from shared.api_client import AvalAIClient, ModelRefusalError, extract_json_from_completion
from persianization.storage import PersianizationStorage
from persianization.config import PersianizationConfig


# English refusal indicator patterns (meta-refusals from model, distinct from translated content)
MODEL_REFUSAL_REASONS = [
    re.compile(r'\b(as an ai|i cannot fulfill|against (our|my) (safety|content) polic|i am unable to assist)\b', re.IGNORECASE),
    re.compile(r'\b(harmful|offensive language|hate speech policy)\b', re.IGNORECASE)
]

# Patterns in English original indicating genuine "cannot" sentences
GENUINE_CANNOT_ORIGINAL = re.compile(r"\b(i cannot|i can't|can not|we cannot|we can't|unable to|impossible)\b", re.IGNORECASE)


def compute_cache_key(text: str, context: Optional[str], model: str, prompt_hash: str) -> str:
    raw = f"{text}||{context or ''}||{model}||{prompt_hash}"
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

    def translate_record(
        self,
        record_id: str,
        raw_text: str,
        raw_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Translates a record using primary model and ordered fallbacks.
        Always sends raw original text to fallback models (no daisy-chaining).
        """
        candidate_models = [self.config.primary_model] + self.config.fallback_models
        # Remove duplicates while preserving order
        ordered_models = []
        for m in candidate_models:
            if m and m not in ordered_models:
                ordered_models.append(m)

        last_error = None
        for model in ordered_models:
            cache_key = compute_cache_key(raw_text, raw_context, model, self.prompt_hash)
            cached_resp = self.storage.get_cache(cache_key)
            if cached_resp:
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

                # Record attempt in SQLite
                status_eval, error_msg = self._evaluate_translation_response(
                    raw_text=raw_text,
                    parsed=parsed,
                    raw_completion=raw_comp
                )

                self.storage.record_attempt(
                    record_id=record_id,
                    step="translation",
                    model=model,
                    usage=res.get("usage", {}),
                    latency_sec=res.get("latency_sec", 0.0),
                    raw_completion=raw_comp,
                    parsed_json=parsed,
                    status=status_eval,
                    error_message=error_msg
                )

                if status_eval in ("translated", "uncertain"):
                    result_data = {
                        "translation_status": status_eval,
                        "text_fa": parsed.get("text_fa"),
                        "context_fa": parsed.get("context_fa"),
                        "reason": parsed.get("reason", ""),
                        "selected_model": model,
                        "error_message": None
                    }
                    self.storage.set_cache(cache_key, result_data)
                    return result_data
                else:
                    # Model refused or failed schema; move to next fallback
                    last_error = error_msg or f"Model '{model}' returned status '{status_eval}'"
                    continue

            except Exception as e:
                last_error = str(e)
                self.storage.record_attempt(
                    record_id=record_id,
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

        # All models exhausted
        return {
            "translation_status": "unresolved",
            "text_fa": None,
            "context_fa": None,
            "reason": f"All translator models exhausted. Last error: {last_error}",
            "selected_model": None,
            "error_message": last_error
        }

    def _evaluate_translation_response(
        self,
        raw_text: str,
        parsed: Optional[Dict[str, Any]],
        raw_completion: str
    ) -> Tuple[str, Optional[str]]:
        """
        Inspects model completion for refusal, unable, schema validity, or genuine "cannot".
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
                # Ensure it's not simply faithful translation of an original "cannot"
                if not GENUINE_CANNOT_ORIGINAL.search(raw_text):
                    return "refused", f"Explicit safety policy refusal detected: {reason}"

        # 3. Check for "نمی‌توانم" in Persian text
        # If the Persian translation has "نمی‌توانم", verify if original has a genuine cannot
        if ("نمی‌توانم" in str(text_fa) or "نمیتوانم" in str(text_fa) or "نمیتونم" in str(text_fa)):
            if not GENUINE_CANNOT_ORIGINAL.search(raw_text):
                # If original didn't have "cannot", but Persian is a single refusal sentence like "من نمی‌توانم این را ترجمه کنم"
                if len(str(text_fa).split()) < 12 and ("ترجمه" in str(text_fa) or "محتوا" in str(text_fa)):
                    return "refused", "Model output Persian refusal sentence instead of translating"

        if status == "uncertain":
            return "uncertain", None

        return "translated", None
