"""
Configuration loader for Project B (White Generation).
Loads generator, quality, and 4-judge models along with recipe configurations.
"""
import os
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv


@dataclass
class WhiteGenerationConfig:
    api_key: str
    base_url: str
    extra_headers: Dict[str, str]

    # Models
    generator_model: str
    quality_model: str
    judge_models: List[str]

    # Model parameters
    generator_route: str
    generator_output_mode: str
    generator_max_tokens: int
    generator_temperature: float
    generator_extra_json: Dict[str, Any]

    quality_route: str
    quality_output_mode: str
    quality_max_tokens: int
    quality_temperature: float
    quality_extra_json: Dict[str, Any]

    judge_route: str
    judge_output_mode: str
    judge_max_tokens: int
    judge_temperature: float

    # Concurrency and budgets
    max_workers: int
    timeout: int
    max_retries: int
    rpm: int
    max_api_calls: int

    # Policies & Prompts
    generation_policy: Dict[str, Any]
    recipe_prompts: Dict[str, Any]
    quality_prompt: str
    offense_judge_prompt: str

    output_dir: str = "outputs/white_generation"

    def validate(self) -> None:
        if not self.generator_model:
            raise ValueError("GENERATOR_MODEL must be specified.")
        if not self.quality_model:
            raise ValueError("WHITE_QUALITY_MODEL must be specified.")
        if len(self.judge_models) != 4:
            raise ValueError(f"Exactly 4 offense judge models required, got {len(self.judge_models)}.")


def load_white_config(env_path: Optional[str] = None) -> WhiteGenerationConfig:
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

    generator_model = os.getenv("GENERATOR_MODEL", "gpt-4o-mini").strip()
    quality_model = os.getenv("WHITE_QUALITY_MODEL", "claude-haiku-4-5").strip()

    judge_models = [
        os.getenv("OFFENSE_JUDGE_1", "gpt-4o-mini").strip(),
        os.getenv("OFFENSE_JUDGE_2", "claude-haiku-4-5").strip(),
        os.getenv("OFFENSE_JUDGE_3", "gemini-2.5-flash").strip(),
        os.getenv("OFFENSE_JUDGE_4", "deepseek-chat").strip()
    ]

    # Prompts & policies
    recipe_prompts_file = os.getenv("RECIPE_PROMPTS_FILE", "white_generation/prompts/recipe_prompts.json")
    quality_prompt_file = os.getenv("WHITE_QUALITY_PROMPT_FILE", "white_generation/prompts/quality_prompt.md")
    judge_prompt_file = os.getenv("OFFENSE_JUDGE_PROMPT_FILE", "white_generation/prompts/offense_judge_prompt.md")
    policy_file = os.getenv("GENERATION_POLICY_FILE", "white_generation/config/generation_policy.json")

    recipe_prompts = {}
    if os.path.exists(recipe_prompts_file):
        with open(recipe_prompts_file, "r", encoding="utf-8") as f:
            recipe_prompts = json.load(f)

    quality_prompt = ""
    if os.path.exists(quality_prompt_file):
        with open(quality_prompt_file, "r", encoding="utf-8") as f:
            quality_prompt = f.read()

    offense_judge_prompt = ""
    if os.path.exists(judge_prompt_file):
        with open(judge_prompt_file, "r", encoding="utf-8") as f:
            offense_judge_prompt = f.read()

    generation_policy = {}
    if os.path.exists(policy_file):
        with open(policy_file, "r", encoding="utf-8") as f:
            generation_policy = json.load(f)

    cfg = WhiteGenerationConfig(
        api_key=api_key,
        base_url=base_url,
        extra_headers=extra_headers,
        generator_model=generator_model,
        quality_model=quality_model,
        judge_models=judge_models,
        generator_route=os.getenv("GENERATOR_API_ROUTE", "chat"),
        generator_output_mode=os.getenv("GENERATOR_OUTPUT_MODE", "json_object"),
        generator_max_tokens=int(os.getenv("GENERATOR_MAX_TOKENS", "4096")),
        generator_temperature=float(os.getenv("GENERATOR_TEMPERATURE", "0.7")),
        generator_extra_json=json.loads(os.getenv("GENERATOR_EXTRA_JSON", "{}")),
        quality_route=os.getenv("WHITE_QUALITY_API_ROUTE", "chat"),
        quality_output_mode=os.getenv("WHITE_QUALITY_OUTPUT_MODE", "json_object"),
        quality_max_tokens=int(os.getenv("WHITE_QUALITY_MAX_TOKENS", "4096")),
        quality_temperature=float(os.getenv("WHITE_QUALITY_TEMPERATURE", "0.0")),
        quality_extra_json=json.loads(os.getenv("WHITE_QUALITY_EXTRA_JSON", "{}")),
        judge_route=os.getenv("OFFENSE_JUDGE_ROUTE", "chat"),
        judge_output_mode=os.getenv("OFFENSE_JUDGE_OUTPUT_MODE", "json_object"),
        judge_max_tokens=int(os.getenv("OFFENSE_JUDGE_MAX_TOKENS", "2048")),
        judge_temperature=float(os.getenv("OFFENSE_JUDGE_TEMPERATURE", "0.0")),
        max_workers=int(os.getenv("MAX_WORKERS", "4")),
        timeout=int(os.getenv("REQUEST_TIMEOUT", "120")),
        max_retries=int(os.getenv("MAX_RETRIES", "2")),
        rpm=int(os.getenv("REQUESTS_PER_MINUTE", "0")),
        max_api_calls=int(os.getenv("MAX_API_CALLS", "0")),
        generation_policy=generation_policy,
        recipe_prompts=recipe_prompts,
        quality_prompt=quality_prompt,
        offense_judge_prompt=offense_judge_prompt,
        output_dir=os.getenv("DEFAULT_OUTPUT_DIR", "outputs/white_generation")
    )
    cfg.validate()
    return cfg
