"""Agent decision tests."""

from __future__ import annotations

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

    def invoke(self, _: object) -> dict[str, object]:
        """Return static payload in agent-like shape.

        Args:
            _: Unused request payload.

        Returns:
            dict[str, object]: Agent-like response dictionary.
        """
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
