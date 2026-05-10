"""Area moderation agent tests."""

from __future__ import annotations

from pathlib import Path

from files_ai.area_agent import AREA_CREATION_SYSTEM_PROMPT
from files_ai.area_agent import AreaAgentParseError
from files_ai.area_agent import build_area_creation_agent_from_settings
from files_ai.area_agent import moderate_area_creation
from files_ai.config import Settings
from files_ai.johnny_decimal import analyze_johnny_decimal_creation
from files_ai.storage import FileRef
from files_ai.storage import LocalFiles


class DummyAreaAgent:
    """Minimal fake moderation agent for deterministic tests."""

    def __init__(self, payload: str) -> None:
        """Store static payload for invoke responses."""
        self.payload = payload
        self.last_request: dict[str, object] | None = None
        self.last_config: dict[str, object] | None = None

    def invoke(self, request: object, **kwargs: object) -> dict[str, object]:
        """Return static payload in an agent-like response shape."""
        if isinstance(request, dict):
            self.last_request = request
        config = kwargs.get("config")
        if isinstance(config, dict):
            self.last_config = config
        return {"output": self.payload}


def test_moderate_area_creation_parses_valid_response(tmp_path: Path) -> None:
    """Parse approval response and sanitize optional replacement folder."""
    files = LocalFiles(tmp_path)
    organized = FileRef("local", "/organized")
    files.make_dir(files.join(organized, "20-29 Council Meetings/23 Youth Council"))
    analysis = analyze_johnny_decimal_creation(
        files=files,
        root=organized,
        folder="Events/Fall Festival/Flyers",
    )
    agent = DummyAreaAgent(
        (
            '{"approved":false,"reasoning":"reuse council path",'
            '"folder":"20-29 Council Meetings/23 Youth Council/23.02 Events",'
            '"confidence":0.85,"quarantine":false}'
        )
    )
    decision = moderate_area_creation(
        agent,
        proposed_folder="90-99 Events/93 Fall Festival/93.01 Flyers",
        creation=analysis,
        tree_snapshot=["20-29 Council Meetings/23 Youth Council/23.01 Agendas"],
        user_context="Youth council events should stay under Council Meetings.",
        source_relative_dir="Ward",
        filename="Fall Festival Plan.pdf",
        extracted_text="fall festival planning notes",
        decision_kind="file",
    )
    assert not decision.approved
    assert decision.folder == "20-29 Council Meetings/23 Youth Council/23.02 Events"
    assert decision.confidence == 0.85
    assert agent.last_config is not None
    assert agent.last_config["tags"] == ["area-agent"]


def test_moderate_area_creation_raises_on_bad_output(tmp_path: Path) -> None:
    """Raise parse error for non-JSON model output."""
    files = LocalFiles(tmp_path)
    organized = FileRef("local", "/organized")
    files.make_dir(files.join(organized, "20-29 Council Meetings/23 Youth Council"))
    analysis = analyze_johnny_decimal_creation(
        files=files,
        root=organized,
        folder="Events/Fall Festival/Flyers",
    )
    agent = DummyAreaAgent("not json")
    try:
        moderate_area_creation(
            agent,
            proposed_folder="Events/Fall Festival/Flyers",
            creation=analysis,
            tree_snapshot=[],
            user_context="",
        )
    except AreaAgentParseError:
        return
    raise AssertionError("Expected AreaAgentParseError")


def test_build_area_creation_agent_uses_area_creation_model(monkeypatch) -> None:
    """Use configured moderation model when building area agent."""
    captured: dict[str, object] = {}

    class FakeChatOllama:
        def __init__(self, **kwargs: object) -> None:
            captured["llm_kwargs"] = kwargs

    def fake_create_agent(**kwargs: object) -> object:
        captured["agent_kwargs"] = kwargs
        return object()

    monkeypatch.setattr("files_ai.area_agent.ChatOllama", FakeChatOllama)
    monkeypatch.setattr("files_ai.area_agent.create_agent", fake_create_agent)
    settings = Settings(
        area_creation_model="kimi-k2.6:cloud",
        ollama_base_url="https://ollama.example",
        ollama_api_key="secret",
    )

    build_area_creation_agent_from_settings(settings)

    llm_kwargs = captured["llm_kwargs"]
    assert isinstance(llm_kwargs, dict)
    assert llm_kwargs["model"] == "kimi-k2.6:cloud"
    assert llm_kwargs["reasoning"] == "medium"
    assert "Authorization" in llm_kwargs["client_kwargs"]["headers"]


def test_area_system_prompt_mentions_caps() -> None:
    """Prompt should encode hard limits and fallback behavior."""
    assert "Top-level areas are capped at 10 total" in AREA_CREATION_SYSTEM_PROMPT
    assert "Never approve creating duplicate 90-99 overflow-like areas" in (
        AREA_CREATION_SYSTEM_PROMPT
    )
