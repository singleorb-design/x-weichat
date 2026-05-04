import pytest

from agent.models.gateway import GatewayError, ModelGateway, build_messages


def test_build_messages_keeps_system_and_user_roles() -> None:
    messages = build_messages(system_prompt="系统", user_prompt="正文")

    assert messages == [
        {"role": "system", "content": "系统"},
        {"role": "user", "content": "正文"},
    ]


class FakeMessage:
    def __init__(self, content: str | None) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: str | None) -> None:
        self.message = FakeMessage(content=content)


class FakeResponse:
    def __init__(self, choices: list[FakeChoice]) -> None:
        self.choices = choices


class FakeCompletions:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.kwargs: dict[str, object] | None = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.chat = type(
            "FakeChat",
            (),
            {"completions": FakeCompletions(response=response)},
        )()


def test_generate_markdown_returns_first_choice_content() -> None:
    client = FakeClient(response=FakeResponse(choices=[FakeChoice(content="# 输出 Markdown")]))
    gateway = ModelGateway(api_key="test-key", base_url="https://example.com", client=client)

    result = gateway.generate_markdown(
        model="qwen-plus",
        system_prompt="系统提示",
        user_prompt="用户提示",
    )

    assert result == "# 输出 Markdown"
    assert client.chat.completions.kwargs["model"] == "qwen-plus"
    assert client.chat.completions.kwargs["messages"] == [
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "用户提示"},
    ]
    assert client.chat.completions.kwargs["temperature"] == 0.3


def test_generate_markdown_raises_for_empty_choices() -> None:
    gateway = ModelGateway(
        api_key="test-key",
        base_url="https://example.com",
        client=FakeClient(response=FakeResponse(choices=[])),
    )

    with pytest.raises(GatewayError, match="choices"):
        gateway.generate_markdown(
            model="qwen-plus",
            system_prompt="系统提示",
            user_prompt="用户提示",
        )


def test_generate_markdown_raises_for_none_content() -> None:
    gateway = ModelGateway(
        api_key="test-key",
        base_url="https://example.com",
        client=FakeClient(response=FakeResponse(choices=[FakeChoice(content=None)])),
    )

    with pytest.raises(GatewayError, match="content"):
        gateway.generate_markdown(
            model="qwen-plus",
            system_prompt="系统提示",
            user_prompt="用户提示",
        )
