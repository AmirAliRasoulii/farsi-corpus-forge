"""
Candidate generation engine executing modular Persian recipes.
Takes Persian seed records and generates clean text candidates.
"""
import json
from typing import Dict, Any, Optional
from shared.api_client import AvalAIClient
from white_generation.config import WhiteGenerationConfig
from white_generation.storage import WhiteGenerationStorage


class CandidateGenerator:
    def __init__(
        self,
        config: WhiteGenerationConfig,
        api_client: AvalAIClient,
        storage: WhiteGenerationStorage
    ):
        self.config = config
        self.client = api_client
        self.storage = storage
        self.recipe_prompts = config.recipe_prompts.get("recipes", {})
        self.sys_inst = config.recipe_prompts.get("system_instruction", "")

    def generate_candidate(
        self,
        candidate_id: str,
        seed_record: Dict[str, Any],
        recipe_key: str
    ) -> Dict[str, Any]:
        """
        Executes a specific recipe on a seed record.
        """
        seed_text = seed_record["text"]
        recipe_info = self.recipe_prompts.get(recipe_key)

        if not recipe_info:
            return {
                "generator_status": "failed",
                "candidate_text": None,
                "candidate_context": None,
                "reason": f"Unknown recipe: '{recipe_key}'"
            }

        prompt_text = f"{recipe_info['prompt']}\n\nمتن بذر:\n{seed_text}"
        messages = [
            {"role": "system", "content": self.sys_inst},
            {"role": "user", "content": prompt_text}
        ]

        try:
            res = self.client.invoke(
                model=self.config.generator_model,
                messages=messages,
                api_route=self.config.generator_route,
                max_tokens=self.config.generator_max_tokens,
                output_mode=self.config.generator_output_mode,
                temperature=self.config.generator_temperature,
                extra_params=self.config.generator_extra_json
            )

            parsed = res.get("parsed_json")
            raw_comp = res.get("raw_completion", "")

            status = "failed"
            error_msg = None
            if parsed:
                status = parsed.get("status", "generated")
            else:
                error_msg = "Failed to parse JSON completion from generator"

            self.storage.record_attempt(
                candidate_id=candidate_id,
                step=f"generation_{recipe_key}",
                model=self.config.generator_model,
                usage=res.get("usage", {}),
                latency_sec=res.get("latency_sec", 0.0),
                raw_completion=raw_comp,
                parsed_json=parsed,
                status=status,
                error_message=error_msg
            )

            if parsed and status == "generated":
                return {
                    "generator_status": "generated",
                    "candidate_text": parsed.get("candidate_text"),
                    "candidate_context": parsed.get("candidate_context"),
                    "reason": parsed.get("reason", "")
                }
            elif parsed and status == "inapplicable":
                return {
                    "generator_status": "inapplicable",
                    "candidate_text": None,
                    "candidate_context": None,
                    "reason": parsed.get("reason", "Recipe inapplicable to this seed")
                }
            else:
                return {
                    "generator_status": "failed",
                    "candidate_text": None,
                    "candidate_context": None,
                    "reason": error_msg or "Generation failed"
                }

        except Exception as e:
            self.storage.record_attempt(
                candidate_id=candidate_id,
                step=f"generation_{recipe_key}",
                model=self.config.generator_model,
                usage={},
                latency_sec=0.0,
                raw_completion="",
                parsed_json=None,
                status="failed",
                error_message=str(e)
            )
            return {
                "generator_status": "failed",
                "candidate_text": None,
                "candidate_context": None,
                "reason": str(e)
            }
