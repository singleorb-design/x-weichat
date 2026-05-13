from __future__ import annotations

from threading import Lock
from time import sleep

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI


REQUEST_TIMEOUT_SECONDS = 900.0
MAX_GENERATION_ATTEMPTS = 3
RETRYABLE_ERRORS = (APIConnectionError, APITimeoutError, InternalServerError)
PROBE_SYSTEM_PROMPT = "你是模型连通性探测器，只回复 OK。"
PROBE_MAX_TOKENS = 8


def _uses_user_only_messages(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized.startswith("qwen-mt-")


def build_messages(*, model: str, system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
    if _uses_user_only_messages(model):
        return [
            {
                "role": "user",
                "content": f"[System]\n{system_prompt}\n\n[User]\n{user_prompt}",
            }
        ]

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


class GatewayError(RuntimeError):
    pass


class ModelGateway:
    """统一封装 OpenAI-compatible 调用。

    这里把超时、重试和响应校验放在一处，避免各 stage 自己处理网络抖动，
    也让流水线日志与 UI 能看到一致的错误语义。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        client: OpenAI | None = None,
    ) -> None:
        # 长文章翻译/改写可能持续数分钟；显式放宽 timeout，
        # 并把重试放到本类里统一处理，这样 UI 与日志拿到的是同一类错误语义。
        self._client = client or OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
        self._request_lock = Lock()

    def generate_markdown(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        request_timeout_seconds: float | None = None,
    ) -> str:
        """对单个 Markdown 任务发起生成请求，并在可重试错误上自动重试。"""
        messages = build_messages(model=model, system_prompt=system_prompt, user_prompt=user_prompt)

        response = self._create_completion(
            model=model,
            messages=messages,
            temperature=0.3,
            request_timeout_seconds=request_timeout_seconds,
        )
        return self._extract_content(response)

    def probe_model(self, *, model: str, stage: str | None = None) -> str:
        """在真正运行阶段前做一次极小请求，提前暴露模型不可达/未开通等问题。"""
        stage_hint = f"stage={stage}" if stage else "stage=unknown"
        response = self._create_completion(
            model=model,
            messages=build_messages(model=model, system_prompt=PROBE_SYSTEM_PROMPT, user_prompt=stage_hint),
            temperature=0.0,
            max_tokens=PROBE_MAX_TOKENS,
        )
        return self._extract_content(response).strip()

    def probe_stage_models(self, stage_models: dict[str, str]) -> dict[str, str]:
        """按阶段探测当前配置的模型，便于启动前快速发现坏链路。"""
        for stage, model in stage_models.items():
            self.probe_model(model=model, stage=stage)
        return dict(stage_models)

    def _create_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None = None,
        request_timeout_seconds: float | None = None,
    ):
        request: dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            request["max_tokens"] = max_tokens

        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            try:
                with self._request_lock:
                    client = (
                        self._client.with_options(timeout=request_timeout_seconds)
                        if request_timeout_seconds is not None
                        else self._client
                    )
                    response = client.chat.completions.create(**request)
                break
            except RETRYABLE_ERRORS:
                if attempt >= MAX_GENERATION_ATTEMPTS:
                    raise
                sleep(1.5 * attempt)

        return response

    def _extract_content(self, response) -> str:
        choices = getattr(response, "choices", None)
        if not choices:
            raise GatewayError("Model response is invalid: choices are empty.")

        message = getattr(choices[0], "message", None)
        if message is None:
            raise GatewayError("Model response is invalid: first choice is missing message.")

        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise GatewayError("Model response is invalid: message content is empty.")

        return content
