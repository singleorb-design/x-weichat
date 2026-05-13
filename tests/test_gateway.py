import pytest
import threading

import agent.models.gateway as gateway_module
from agent.models.gateway import GatewayError, ModelGateway, build_messages


def test_build_messages_keeps_system_and_user_roles() -> None:
    messages = build_messages(model="gpt-4.1-mini", system_prompt="系统", user_prompt="正文")

    assert messages == [
        {"role": "system", "content": "系统"},
        {"role": "user", "content": "正文"},
    ]


def test_build_messages_inlines_system_prompt_for_qwen_mt_plus() -> None:
    messages = build_messages(model="qwen-mt-plus", system_prompt="系统", user_prompt="正文")

    assert messages == [
        {"role": "user", "content": "[System]\n系统\n\n[User]\n正文"},
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
        self.last_timeout: float | None = None
        self.chat = type(
            "FakeChat",
            (),
            {"completions": FakeCompletions(response=response)},
        )()

    def with_options(self, *, timeout: float):
        self.last_timeout = timeout
        return self


class FlakyCompletions:
    def __init__(self, results: list[object]) -> None:
        self.results = results
        self.calls = 0

    def create(self, **kwargs):
        result = self.results[self.calls]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


class FlakyClient:
    def __init__(self, results: list[object]) -> None:
        self.chat = type(
            "FakeChat",
            (),
            {"completions": FlakyCompletions(results=results)},
        )()


def test_generate_markdown_returns_first_choice_content() -> None:
    client = FakeClient(response=FakeResponse(choices=[FakeChoice(content="# 输出 Markdown")]))
    gateway = ModelGateway(api_key="test-key", base_url="https://example.com", client=client)

    result = gateway.generate_markdown(
        model="qwen-mt-plus",
        system_prompt="系统提示",
        user_prompt="用户提示",
    )

    assert result == "# 输出 Markdown"
    assert client.chat.completions.kwargs["model"] == "qwen-mt-plus"
    assert client.chat.completions.kwargs["messages"] == [
        {"role": "user", "content": "[System]\n系统提示\n\n[User]\n用户提示"},
    ]
    assert client.chat.completions.kwargs["temperature"] == 0.3


def test_generate_markdown_uses_per_request_timeout_when_provided() -> None:
    client = FakeClient(response=FakeResponse(choices=[FakeChoice(content="# 输出 Markdown")]))
    gateway = ModelGateway(api_key="test-key", base_url="https://example.com", client=client)

    gateway.generate_markdown(
        model="qwen-mt-plus",
        system_prompt="系统提示",
        user_prompt="用户提示",
        request_timeout_seconds=12.5,
    )

    assert client.last_timeout == 12.5


def test_generate_markdown_raises_for_empty_choices() -> None:
    gateway = ModelGateway(
        api_key="test-key",
        base_url="https://example.com",
        client=FakeClient(response=FakeResponse(choices=[])),
    )

    with pytest.raises(GatewayError, match="choices"):
        gateway.generate_markdown(
            model="qwen-mt-plus",
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
            model="qwen-mt-plus",
            system_prompt="系统提示",
            user_prompt="用户提示",
        )


def test_generate_markdown_retries_retryable_gateway_errors(monkeypatch) -> None:
    client = FlakyClient(
        results=[
            RuntimeError("temporary disconnect"),
            FakeResponse(choices=[FakeChoice(content="# restored")]),
        ]
    )
    gateway = ModelGateway(api_key="test-key", base_url="https://example.com", client=client)

    monkeypatch.setattr(gateway_module, "RETRYABLE_ERRORS", (RuntimeError,))
    monkeypatch.setattr(gateway_module, "sleep", lambda *_args, **_kwargs: None)

    result = gateway.generate_markdown(
        model="qwen-mt-plus",
        system_prompt="系统提示",
        user_prompt="用户提示",
    )

    assert result == "# restored"
    assert client.chat.completions.calls == 2


def test_probe_model_uses_small_completion_request() -> None:
    client = FakeClient(response=FakeResponse(choices=[FakeChoice(content="OK")]))
    gateway = ModelGateway(api_key="test-key", base_url="https://example.com", client=client)

    result = gateway.probe_model(model="qwen-mt-plus", stage="light-polish")

    assert result == "OK"
    assert client.chat.completions.kwargs["model"] == "qwen-mt-plus"
    assert client.chat.completions.kwargs["temperature"] == 0.0
    assert client.chat.completions.kwargs["max_tokens"] == 8
    assert client.chat.completions.kwargs["messages"] == [
        {
            "role": "user",
            "content": "[System]\n你是模型连通性探测器，只回复 OK。\n\n[User]\nstage=light-polish",
        },
    ]


def test_probe_stage_models_checks_each_stage() -> None:
    client = FakeClient(response=FakeResponse(choices=[FakeChoice(content="OK")]))
    gateway = ModelGateway(api_key="test-key", base_url="https://example.com", client=client)
    probe_calls: list[tuple[str, str | None]] = []

    def fake_probe_model(*, model: str, stage: str | None = None) -> str:
        probe_calls.append((model, stage))
        return "OK"

    gateway.probe_model = fake_probe_model  # type: ignore[method-assign]

    results = gateway.probe_stage_models(
        {
            "translate": "qwen-mt-plus",
            "light-polish": "qwen-mt-plus",
        }
    )

    assert results == {
        "translate": "qwen-mt-plus",
        "light-polish": "qwen-mt-plus",
    }
    assert probe_calls == [
        ("qwen-mt-plus", "translate"),
        ("qwen-mt-plus", "light-polish"),
    ]


def test_generate_markdown_serializes_concurrent_requests_through_shared_gateway() -> None:
    class BlockingCompletions:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0
            self.first_started = threading.Event()
            self.second_started = threading.Event()
            self.release = threading.Event()
            self.state_lock = threading.Lock()

        def create(self, **kwargs):
            del kwargs
            with self.state_lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                if self.active == 1:
                    self.first_started.set()
                if self.active >= 2:
                    self.second_started.set()

            assert self.release.wait(timeout=1.0)

            with self.state_lock:
                self.active -= 1

            return FakeResponse(choices=[FakeChoice(content="# ok")])

    completions = BlockingCompletions()
    client = type(
        "BlockingClient",
        (),
        {"chat": type("BlockingChat", (), {"completions": completions})()},
    )()
    gateway = ModelGateway(api_key="test-key", base_url="https://example.com", client=client)
    results: list[str] = []

    def run_request() -> None:
        results.append(
            gateway.generate_markdown(
                model="qwen-mt-plus",
                system_prompt="系统提示",
                user_prompt="用户提示",
            )
        )

    first = threading.Thread(target=run_request)
    second = threading.Thread(target=run_request)

    first.start()
    assert completions.first_started.wait(timeout=1.0)
    second.start()

    assert not completions.second_started.wait(timeout=0.2)

    completions.release.set()
    first.join(timeout=1.0)
    second.join(timeout=1.0)

    assert results == ["# ok", "# ok"]
    assert completions.max_active == 1
