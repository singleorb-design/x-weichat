from openai import OpenAI


def build_messages(system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


class GatewayError(RuntimeError):
    pass


class ModelGateway:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        client: OpenAI | None = None,
    ) -> None:
        self._client = client or OpenAI(api_key=api_key, base_url=base_url)

    def generate_markdown(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        response = self._client.chat.completions.create(
            model=model,
            messages=build_messages(system_prompt, user_prompt),
            temperature=0.3,
        )
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
