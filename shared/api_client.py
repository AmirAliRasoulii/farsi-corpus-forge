"""
Unified AvalAI / OpenAI compatible HTTP API client.
Features:
- Authentication & permission error immediate failure (401/403)
- Exponential backoff with jitter on 429 / 5xx
- Full token usage tracking per call
- Zero API key leaks in logs/manifests
- Offline mock handler hook for tests and mock demo
- Robust JSON extraction from LLM completions
"""
import os
import re
import json
import time
import random
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Callable, List, Tuple


class AuthenticationError(Exception):
    """Raised on 401 / 403 responses. Halts execution immediately."""
    pass


class ModelRefusalError(Exception):
    """Raised when the model explicitly refuses or signals unable to complete."""
    pass


def extract_json_from_completion(text: str) -> Dict[str, Any]:
    """
    Extracts and parses JSON object from an LLM response string.
    Handles Markdown code fences (```json ... ```) or embedded JSON text.
    """
    if not text:
        raise ValueError("Empty completion text; cannot extract JSON.")

    cleaned = text.strip()

    # If wrapped in code block
    fence_pattern = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', cleaned, re.IGNORECASE)
    if fence_pattern:
        cleaned = fence_pattern.group(1).strip()

    # Direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Search for first '{' and matching last '}'
    start_idx = cleaned.find('{')
    end_idx = cleaned.rfind('}')
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        candidate = cleaned[start_idx:end_idx + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Failed to extract valid JSON from completion: {text[:200]}...")


class AvalAIClient:
    """
    Client for AvalAI / OpenAI-compatible LLM endpoints.
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.avalai.ir/v1",
        timeout: int = 120,
        max_retries: int = 2,
        extra_headers: Optional[Dict[str, str]] = None,
        rate_limiter = None,
        mock_handler: Optional[Callable[[str, List[Dict[str, str]], Dict[str, Any]], Dict[str, Any]]] = None
    ):
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "https://api.avalai.ir/v1")).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.extra_headers = extra_headers or {}
        self.rate_limiter = rate_limiter
        self.mock_handler = mock_handler

        # Cumulative usage metrics
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.total_api_calls = 0

    def invoke(
        self,
        model: str,
        messages: List[Dict[str, str]],
        api_route: str = "chat",
        max_tokens: int = 4096,
        token_field: str = "max_completion_tokens",
        output_mode: str = "json_object",
        reasoning_effort: Optional[str] = None,
        temperature: float = 0.0,
        extra_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Sends request to LLM, handling retries, tokens, and errors.
        Returns dict with:
          - raw_completion: str
          - parsed_json: Optional[dict]
          - usage: dict (prompt_tokens, completion_tokens, total_tokens)
          - model: str
          - latency_sec: float
        """
        if self.mock_handler:
            return self._invoke_mock(model, messages, extra_params or {})

        if not self.api_key:
            raise AuthenticationError("LLM_API_KEY is not set or empty. Please configure credentials in .env.")

        # Determine endpoint URL
        if api_route == "responses":
            url = f"{self.base_url}/responses"
        else:
            url = f"{self.base_url}/chat/completions"

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
        }

        if temperature is not None:
            payload["temperature"] = temperature

        if api_route != "responses":
            if token_field == "max_tokens":
                payload["max_tokens"] = max_tokens
            else:
                payload["max_completion_tokens"] = max_tokens

            if reasoning_effort:
                payload["reasoning_effort"] = reasoning_effort

            if output_mode == "json_object":
                payload["response_format"] = {"type": "json_object"}
        else:
            if reasoning_effort:
                payload["reasoning"] = {"effort": reasoning_effort}

        if extra_params:
            for k, v in extra_params.items():
                if k not in payload:
                    payload[k] = v

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "TranslateOffsetData/1.0"
        }
        headers.update(self.extra_headers)

        body_bytes = json.dumps(payload).encode("utf-8")
        retries = 0

        while True:
            # Check rate limiter / budget before sending request
            if self.rate_limiter:
                self.rate_limiter.acquire()

            t0 = time.time()
            try:
                self.total_api_calls += 1
                req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp_bytes = resp.read()
                    data = json.loads(resp_bytes.decode("utf-8"))

                latency = round(time.time() - t0, 3)

                # Extract completion text
                completion_text = ""
                if "choices" in data and len(data["choices"]) > 0:
                    choice = data["choices"][0]
                    msg = choice.get("message", {})
                    completion_text = msg.get("content") or ""
                elif "response" in data:
                    completion_text = data["response"]
                elif "text" in data:
                    completion_text = data["text"]

                # Extract usage
                usage_info = data.get("usage", {})
                prompt_toks = usage_info.get("prompt_tokens", 0)
                comp_toks = usage_info.get("completion_tokens", 0)
                total_toks = usage_info.get("total_tokens", prompt_toks + comp_toks)

                self.total_prompt_tokens += prompt_toks
                self.total_completion_tokens += comp_toks
                self.total_tokens += total_toks

                parsed = None
                try:
                    parsed = extract_json_from_completion(completion_text)
                except Exception:
                    pass

                return {
                    "raw_completion": completion_text,
                    "parsed_json": parsed,
                    "usage": {
                        "prompt_tokens": prompt_toks,
                        "completion_tokens": comp_toks,
                        "total_tokens": total_toks
                    },
                    "model": model,
                    "latency_sec": latency,
                    "raw_response": data
                }

            except urllib.error.HTTPError as e:
                # 401 Unauthorized or 403 Forbidden: halt immediately
                if e.code in (401, 403):
                    raise AuthenticationError(
                        f"HTTP {e.code} Authentication/Permission failed for model '{model}'. "
                        "Check your LLM_API_KEY. Execution stopped immediately to prevent account lockout."
                    ) from e

                # 429 Too Many Requests or 5xx Server Error: retry with backoff
                if retries < self.max_retries and (e.code == 429 or e.code >= 500):
                    retries += 1
                    backoff = (2 ** retries) + random.uniform(0.5, 1.5)
                    time.sleep(backoff)
                    continue

                # Unrecoverable HTTP error
                err_body = e.read().decode("utf-8", errors="replace") if hasattr(e, 'read') else str(e)
                raise RuntimeError(f"HTTP {e.code} error from LLM endpoint ({model}): {err_body}") from e

            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if retries < self.max_retries:
                    retries += 1
                    backoff = (2 ** retries) + random.uniform(0.5, 1.5)
                    time.sleep(backoff)
                    continue
                raise RuntimeError(f"Network error calling LLM endpoint ({model}): {str(e)}") from e

    def _invoke_mock(self, model: str, messages: List[Dict[str, str]], extra_params: Dict[str, Any]) -> Dict[str, Any]:
        """Handles mock invocation for tests and offline demonstrations."""
        if self.rate_limiter:
            self.rate_limiter.acquire()
        t0 = time.time()
        self.total_api_calls += 1
        res = self.mock_handler(model, messages, extra_params)
        latency = round(time.time() - t0, 3)

        raw = res.get("raw_completion", "")
        usage = res.get("usage", {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80})
        self.total_prompt_tokens += usage.get("prompt_tokens", 0)
        self.total_completion_tokens += usage.get("completion_tokens", 0)
        self.total_tokens += usage.get("total_tokens", 0)

        parsed = res.get("parsed_json")
        if parsed is None and raw:
            try:
                parsed = extract_json_from_completion(raw)
            except Exception:
                pass

        return {
            "raw_completion": raw,
            "parsed_json": parsed,
            "usage": usage,
            "model": model,
            "latency_sec": latency,
            "raw_response": res
        }

    def get_cumulative_usage(self) -> Dict[str, int]:
        return {
            "total_api_calls": self.total_api_calls,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens
        }
