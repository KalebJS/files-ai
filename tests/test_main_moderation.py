"""Main orchestration moderation helper tests."""

from __future__ import annotations

from pathlib import Path

from files_ai.__main__ import _moderate_destination_if_needed
from files_ai.storage import FileRef
from files_ai.storage import LocalFiles
from files_ai.store import Store
from files_ai.tools import OrganizerTools
from files_ai.tools import ToolContext


class DummyAreaAgent:
    """Fake area moderation agent with fixed response."""

    def __init__(self, payload: str) -> None:
        """Store static payload for invoke responses."""
        self.payload = payload
        self.calls = 0

    def invoke(self, request: object, **_: object) -> dict[str, object]:
        """Return static payload while counting moderation invocations."""
        self.calls += 1
        return {"output": self.payload}


def _build_tools(tmp_path: Path) -> OrganizerTools:
    files = LocalFiles(tmp_path)
    organized = FileRef("local", "/organized")
    quarantine = FileRef("local", "/quarantine")
    files.make_dir(organized)
    files.make_dir(quarantine)
    store = Store(tmp_path / "state.db")
    return OrganizerTools(
        ToolContext(
            files=files,
            store=store,
            organized_root=organized,
            quarantine_root=quarantine,
            dry_run=True,
        )
    )


def test_moderation_helper_skips_new_id_only(tmp_path: Path) -> None:
    """Do not call area agent when only a new ID is needed."""
    tools = _build_tools(tmp_path)
    tools.ctx.files.make_dir(
        tools.ctx.files.join(
            tools.ctx.organized_root,
            "20-29 Council Meetings/23 Youth Council/23.01 Agendas",
        )
    )
    agent = DummyAreaAgent(
        '{"approved":true,"reasoning":"ok","folder":null,"confidence":1.0,'
        '"quarantine":false}'
    )
    outcome = _moderate_destination_if_needed(
        proposed_folder="Council Meetings/Youth Council/Minutes",
        area_agent=agent,
        tools=tools,
        snapshot=["20-29 Council Meetings/23 Youth Council/23.01 Agendas"],
        source_relative_dir="Ward",
        user_context="",
        filename="minutes.pdf",
        extracted_text="minutes text",
        decision_kind="file",
    )
    assert outcome.folder == "Council Meetings/Youth Council/Minutes"
    assert not outcome.quarantine
    assert agent.calls == 0


def test_moderation_helper_applies_replacement_folder(tmp_path: Path) -> None:
    """Use replacement path when area moderation rejects creation."""
    tools = _build_tools(tmp_path)
    tools.ctx.files.make_dir(
        tools.ctx.files.join(
            tools.ctx.organized_root, "20-29 Council Meetings/23 Youth Council"
        )
    )
    agent = DummyAreaAgent(
        (
            '{"approved":false,"reasoning":"use council meetings",'
            '"folder":"20-29 Council Meetings/23 Youth Council/23.02 Events",'
            '"confidence":0.91,"quarantine":false}'
        )
    )
    outcome = _moderate_destination_if_needed(
        proposed_folder="90-99 Youth Council/92 Agendas/92.01 Youth Council",
        area_agent=agent,
        tools=tools,
        snapshot=["20-29 Council Meetings/23 Youth Council/23.01 Agendas"],
        source_relative_dir="Ward",
        user_context="",
        filename="agenda.pdf",
        extracted_text="youth council agenda",
        decision_kind="file",
    )
    assert outcome.folder == "20-29 Council Meetings/23 Youth Council/23.02 Events"
    assert not outcome.quarantine
    assert agent.calls == 1
