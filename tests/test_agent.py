"""Agent decision tests."""

from __future__ import annotations

import os

import pytest

from files_ai.agent import AgentParseError
from files_ai.agent import decide_folder


class DummyAgent:
    """Minimal fake agent used for deterministic tests."""

    def __init__(self, payload: str) -> None:
        """Store response payload.

        Args:
            payload: Static output text to return from `invoke`.
        """
        self.payload = payload
        self.last_request: dict[str, object] | None = None
        self.last_config: dict[str, object] | None = None

    def invoke(self, request: object, **kwargs: object) -> dict[str, object]:
        """Return static payload in agent-like shape.

        Args:
            request: Request payload.
            **kwargs: Optional invoke keyword arguments.

        Returns:
            dict[str, object]: Agent-like response dictionary.
        """
        if isinstance(request, dict):
            self.last_request = request
        config = kwargs.get("config")
        if isinstance(config, dict):
            self.last_config = config
        return {"output": self.payload}


def test_decide_folder_parses_json_output() -> None:
    """Parse valid JSON output into a typed decision."""
    agent = DummyAgent(
        (
            '{"folder":"Finance/Invoices","reasoning":"invoice keywords",'
            '"confidence":0.9,"quarantine":false}'
        )
    )
    decision = decide_folder(
        agent,
        filename="invoice.txt",
        extracted_text="invoice balance due",
        tree_snapshot=[],
    )
    assert decision.folder == "Finance/Invoices"
    assert decision.confidence == 0.9
    assert not decision.quarantine


def test_decide_folder_raises_on_invalid_output() -> None:
    """Raise parse errors when model output is not parseable JSON."""
    agent = DummyAgent("not json")
    with pytest.raises(AgentParseError):
        decide_folder(
            agent,
            filename="receipt.txt",
            extracted_text="receipt payment",
            tree_snapshot=[],
        )


def test_decide_folder_clamps_confidence() -> None:
    """Clamp confidence values above one."""
    agent = DummyAgent(
        (
            '{"folder":"Finance/Invoices","reasoning":"invoice keywords",'
            '"confidence":1.8,"quarantine":false}'
        )
    )
    decision = decide_folder(
        agent,
        filename="invoice.txt",
        extracted_text="invoice balance due",
        tree_snapshot=[],
    )
    assert decision.confidence == 1.0


def test_decide_folder_sanitizes_folder() -> None:
    """Strip unsafe folder characters from model output."""
    agent = DummyAgent(
        (
            '{"folder":"Finance/Inv@l!d/..//2026","reasoning":"invoice keywords",'
            '"confidence":0.9,"quarantine":false}'
        )
    )
    decision = decide_folder(
        agent,
        filename="invoice.txt",
        extracted_text="invoice balance due",
        tree_snapshot=[],
    )
    assert decision.folder == "Finance/Invld/2026"


def test_decide_folder_prompt_discourages_unsorted() -> None:
    """Exclude Unsorted from tree context and include source folder signal."""
    agent = DummyAgent(
        (
            '{"folder":"Code/C++","reasoning":"source dir and extension",'
            '"confidence":0.9,"quarantine":false}'
        )
    )
    decide_folder(
        agent,
        filename="Lab8.cpp",
        extracted_text="data structure assignment",
        tree_snapshot=["Unsorted", "Finance/Invoices"],
        source_relative_dir="Security",
        user_context="You manage files for Acme Finance.",
    )
    assert agent.last_request is not None
    messages = agent.last_request.get("messages")
    assert isinstance(messages, list)
    content = messages[0]["content"]
    assert "# Task" in content
    assert "## File metadata" in content
    assert "**source_relative_dir**: `Security`" in content
    assert "**unsorted_present**: `True`" in content
    assert "## Existing tree" in content
    assert '"Finance"' in content
    assert '"Invoices"' in content
    assert "## User context" in content
    assert "```markdown" in content
    assert "You manage files for Acme Finance." in content
    assert "## Extracted text" in content
    assert "```text" in content


def test_decide_folder_sends_trace_metadata() -> None:
    """Attach LangSmith-compatible tags and metadata to invoke config."""
    agent = DummyAgent(
        (
            '{"folder":"Code/C++","reasoning":"source dir and extension",'
            '"confidence":0.9,"quarantine":false}'
        )
    )
    decide_folder(
        agent,
        filename="Lab8.cpp",
        extracted_text="data structure assignment",
        tree_snapshot=["Unsorted", "Finance/Invoices"],
        source_relative_dir="Security",
    )
    assert agent.last_config == {
        "tags": ["file-agent"],
        "metadata": {
            "filename": "Lab8.cpp",
            "source_relative_dir": "Security",
            "tree_size": 2,
        },
    }


def test_decide_folder_parses_optional_filename() -> None:
    """Parse optional filename output from model response."""
    agent = DummyAgent(
        (
            '{"folder":"Finance/Invoices","reasoning":"invoice keywords",'
            '"confidence":0.9,"quarantine":false,'
            '"filename":"2026-04 Invoice #1042.pdf"}'
        )
    )
    decision = decide_folder(
        agent,
        filename="invoice.txt",
        extracted_text="invoice balance due",
        tree_snapshot=[],
    )
    assert decision.filename == "2026-04 Invoice 1042.pdf"


def test_decide_folder_sanitizes_optional_filename() -> None:
    """Strip unsafe/path characters and normalize basename-only filename."""
    agent = DummyAgent(
        (
            '{"folder":"Finance/Invoices","reasoning":"invoice keywords",'
            '"confidence":0.9,"quarantine":false,'
            '"filename":"nested\\\\..\\\\scan<>?.pdf"}'
        )
    )
    decision = decide_folder(
        agent,
        filename="scan.pdf",
        extracted_text="invoice balance due",
        tree_snapshot=[],
    )
    assert decision.filename == "scan.pdf"


def test_decide_folder_prompt_includes_filename_policy() -> None:
    """Include explicit rename policy guidance in the routing prompt."""
    agent = DummyAgent(
        (
            '{"folder":"Code/C++","reasoning":"source dir and extension",'
            '"confidence":0.9,"quarantine":false,"filename":null}'
        )
    )
    decide_folder(
        agent,
        filename="Lab8.cpp",
        extracted_text="data structure assignment",
        tree_snapshot=["10-19 Code/10 Projects/10.01 Projects/main.py"],
        source_relative_dir="Security",
    )
    assert agent.last_request is not None
    messages = agent.last_request.get("messages")
    assert isinstance(messages, list)
    content = messages[0]["content"]
    assert "## Filename policy" in content
    assert "filename is already good" in content.lower()


def test_build_agent_configures_langsmith(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set tracing env vars from runtime settings when tracing is enabled."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGSMITH_ENDPOINT", raising=False)
    captured: dict[str, object] = {}

    class FakeChatOllama:
        """Test double for ChatOllama constructor."""

        def __init__(self, **kwargs: object) -> None:
            captured["llm_kwargs"] = kwargs

    def fake_create_agent(**kwargs: object) -> object:
        captured["agent_kwargs"] = kwargs
        return object()

    monkeypatch.setattr("files_ai.agent.ChatOllama", FakeChatOllama)
    monkeypatch.setattr("files_ai.agent.create_agent", fake_create_agent)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "files-ai-tests")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

    from files_ai.agent import build_agent
    from files_ai.config import Settings

    settings = Settings()
    build_agent(settings)

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "test-key"
    assert os.environ["LANGSMITH_PROJECT"] == "files-ai-tests"
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://api.smith.langchain.com"
    assert isinstance(captured["llm_kwargs"], dict)
    assert isinstance(captured["agent_kwargs"], dict)
