"""
Configuration loader and validator for Persianization pipeline.
Enforces strict model independence across primary translator, all fallback models,
and dual quality evaluators (QUALITY_MODEL_1 and QUALITY_MODEL_2).
"""
import os
import json
import hashlib
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv


@dataclass
class PersianizationConfig:
    # API credentials and endpoints
    api_key: str
    base_url: str
    extra_headers: Dict[str, str]

    # Models
    primary_model: str
    fallback_models: List[str]
    quality_model_1: str
    quality_model_2: str

    # Model parameters for translator
    translator_route: str
    translator_output_mode: str
    translator_max_tokens: int
    translator_token_field: str
    translator_temperature: float
    translator_extra_json: Dict[str, Any]

    # Model parameters for quality judge 1
    quality_1_route: str
    quality_1_output_mode: str
    quality_1_max_tokens: int
    quality_1_token_field: str
    quality_1_temperature: float
    quality_1_extra_json: Dict[str, Any]

    # Model parameters for quality judge 2
    quality_2_route: str
    quality_2_output_mode: str
    quality_2_max_tokens: int
    quality_2_token_field: str
    quality_2_temperature: float
    quality_2_extra_json: Dict[str, Any]

    # Batching and Concurrency
    input_batch_size: int
    max_concurrent_requests: int
    timeout: int
    max_retries: int
    rpm: int
    max_api_calls: int

    # Quality policy & Sampling
    quality_accept_threshold: float
    human_audit_sample_rate: float
    second_judge_random_sample_rate: float
    second_judge_targeted_enabled: bool
    review_policy: Dict[str, Any]

    # Circuit Breaker
    circuit_breaker_enabled: bool
    circuit_breaker_max_failure_rate: float
    circuit_breaker_min_observations: int

    # Prompts & Hashes
    translator_prompt: str
    quality_prompt: str
    prompt_version: str = "v2.0"
    policy_hash: str = ""
    output_dir: str = "outputs/persianization"

    @property
    def quality_model(self) -> str:
        return self.quality_model_1

    def validate(self) -> None:
        """Validates critical constraints and model independence."""
        if not self.primary_model:
            raise ValueError("TRANSLATOR_PRIMARY_MODEL must be configured.")
        if not self.quality_model_1:
            raise ValueError("QUALITY_MODEL_1 must be configured.")
        if not self.quality_model_2:
            raise ValueError("QUALITY_MODEL_2 must be configured.")

        # Check that Judge 1 and Judge 2 have distinct model IDs
        if self.quality_model_1.strip() == self.quality_model_2.strip():
            raise ValueError(
                f"INDEPENDENCE VIOLATION: QUALITY_MODEL_1 and QUALITY_MODEL_2 must have distinct model IDs "
                f"(both set to '{self.quality_model_1}')."
            )

        # Check that neither Quality Model matches the Primary Translator
        if self.primary_model.strip() == self.quality_model_1.strip():
            raise ValueError(
                f"INDEPENDENCE VIOLATION: Primary translator model ('{self.primary_model}') "
                f"is identical to QUALITY_MODEL_1."
            )
        if self.primary_model.strip() == self.quality_model_2.strip():
            raise ValueError(
                f"INDEPENDENCE VIOLATION: Primary translator model ('{self.primary_model}') "
                f"is identical to QUALITY_MODEL_2."
            )

        # Check that neither Quality Model matches ANY of the Fallback Models
        for idx, fb_model in enumerate(self.fallback_models, start=1):
            if fb_model.strip() == self.quality_model_1.strip():
                raise ValueError(
                    f"INDEPENDENCE VIOLATION: Fallback model #{idx} ('{fb_model}') "
                    f"is identical to QUALITY_MODEL_1 ('{self.quality_model_1}'). "
                    "Quality evaluators must remain independent of all possible generator models."
                )
            if fb_model.strip() == self.quality_model_2.strip():
                raise ValueError(
                    f"INDEPENDENCE VIOLATION: Fallback model #{idx} ('{fb_model}') "
                    f"is identical to QUALITY_MODEL_2 ('{self.quality_model_2}'). "
                    "Quality evaluators must remain independent of all possible generator models."
                )


def load_config(env_path: Optional[str] = None) -> PersianizationConfig:
    """Loads configuration from environment / .env file."""
    if env_path and os.path.exists(env_path):
        load_dotenv(env_path, override=True)
    else:
        load_dotenv()

    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "https://api.avalai.ir/v1")

    extra_headers_str = os.getenv("EXTRA_HEADERS", "{}")
    try:
        extra_headers = json.loads(extra_headers_str)
    except Exception:
        extra_headers = {}

    primary_model = os.getenv("TRANSLATOR_PRIMARY_MODEL", "gpt-4o-mini").strip()
    fallbacks_raw = os.getenv("TRANSLATOR_FALLBACK_MODELS", "claude-haiku-4-5,gemini-2.5-flash")
    fallback_models = [m.strip() for m in fallbacks_raw.split(",") if m.strip()]

    # Dual quality evaluators
    quality_model_1 = os.getenv("QUALITY_MODEL_1", os.getenv("QUALITY_MODEL", "deepseek-chat")).strip()
    quality_model_2 = os.getenv("QUALITY_MODEL_2", "command-r-plus").strip()

    # Prompts
    prompt_tr_path = os.getenv("PROMPT_TRANSLATOR_FILE", "persianization/prompts/translator_prompt.md")
    prompt_ql_path = os.getenv("PROMPT_QUALITY_FILE", "persianization/prompts/quality_prompt.md")
    policy_path = os.getenv("REVIEW_POLICY_FILE", "persianization/config/review_policy.json")

    translator_prompt = ""
    if os.path.exists(prompt_tr_path):
        with open(prompt_tr_path, "r", encoding="utf-8") as f:
            translator_prompt = f.read()

    quality_prompt = ""
    if os.path.exists(prompt_ql_path):
        with open(prompt_ql_path, "r", encoding="utf-8") as f:
            quality_prompt = f.read()

    review_policy = {}
    policy_hash = ""
    if os.path.exists(policy_path):
        with open(policy_path, "r", encoding="utf-8") as f:
            policy_content = f.read()
            review_policy = json.loads(policy_content)
            policy_hash = hashlib.sha256(policy_content.encode("utf-8")).hexdigest()[:10]

    cfg = PersianizationConfig(
        api_key=api_key,
        base_url=base_url,
        extra_headers=extra_headers,
        primary_model=primary_model,
        fallback_models=fallback_models,
        quality_model_1=quality_model_1,
        quality_model_2=quality_model_2,
        translator_route=os.getenv("TRANSLATOR_API_ROUTE", "chat"),
        translator_output_mode=os.getenv("TRANSLATOR_OUTPUT_MODE", "json_object"),
        translator_max_tokens=int(os.getenv("TRANSLATOR_MAX_TOKENS", "4096")),
        translator_token_field=os.getenv("TRANSLATOR_TOKEN_FIELD", "max_completion_tokens"),
        translator_temperature=float(os.getenv("TRANSLATOR_TEMPERATURE", "0.1")),
        translator_extra_json=json.loads(os.getenv("TRANSLATOR_EXTRA_JSON", "{}")),
        quality_1_route=os.getenv("QUALITY_1_API_ROUTE", "chat"),
        quality_1_output_mode=os.getenv("QUALITY_1_OUTPUT_MODE", "json_object"),
        quality_1_max_tokens=int(os.getenv("QUALITY_1_MAX_TOKENS", "4096")),
        quality_1_token_field=os.getenv("QUALITY_1_TOKEN_FIELD", "max_completion_tokens"),
        quality_1_temperature=float(os.getenv("QUALITY_1_TEMPERATURE", "0.0")),
        quality_1_extra_json=json.loads(os.getenv("QUALITY_1_EXTRA_JSON", "{}")),
        quality_2_route=os.getenv("QUALITY_2_API_ROUTE", "chat"),
        quality_2_output_mode=os.getenv("QUALITY_2_OUTPUT_MODE", "json_object"),
        quality_2_max_tokens=int(os.getenv("QUALITY_2_MAX_TOKENS", "4096")),
        quality_2_token_field=os.getenv("QUALITY_2_TOKEN_FIELD", "max_completion_tokens"),
        quality_2_temperature=float(os.getenv("QUALITY_2_TEMPERATURE", "0.0")),
        quality_2_extra_json=json.loads(os.getenv("QUALITY_2_EXTRA_JSON", "{}")),
        input_batch_size=int(os.getenv("INPUT_BATCH_SIZE", "50")),
        max_concurrent_requests=int(os.getenv("MAX_CONCURRENT_REQUESTS", os.getenv("MAX_WORKERS", "4"))),
        timeout=int(os.getenv("REQUEST_TIMEOUT", "120")),
        max_retries=int(os.getenv("MAX_RETRIES", "2")),
        rpm=int(os.getenv("REQUESTS_PER_MINUTE", "0")),
        max_api_calls=int(os.getenv("MAX_API_CALLS", "0")),
        quality_accept_threshold=float(os.getenv("QUALITY_ACCEPT_THRESHOLD", str(review_policy.get("min_dimension_score", 4.0)))),
        human_audit_sample_rate=float(os.getenv("HUMAN_AUDIT_SAMPLE_RATE", str(review_policy.get("human_audit_sample_rate", 0.10)))),
        second_judge_random_sample_rate=float(os.getenv("SECOND_JUDGE_SAMPLE_RATE", "0.10")),
        second_judge_targeted_enabled=os.getenv("SECOND_JUDGE_TARGETED_ENABLED", "true").lower() == "true",
        review_policy=review_policy,
        circuit_breaker_enabled=os.getenv("CIRCUIT_BREAKER_ENABLED", "true").lower() == "true",
        circuit_breaker_max_failure_rate=float(os.getenv("CIRCUIT_BREAKER_MAX_FAILURE_RATE", "0.40")),
        circuit_breaker_min_observations=int(os.getenv("CIRCUIT_BREAKER_MIN_OBSERVATIONS", "10")),
        translator_prompt=translator_prompt,
        quality_prompt=quality_prompt,
        policy_hash=policy_hash,
        output_dir=os.getenv("DEFAULT_OUTPUT_DIR", "outputs/persianization")
    )

    cfg.validate()
    return cfg
