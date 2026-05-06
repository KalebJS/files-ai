from __future__ import annotations

from files_ai.agent import decide_folder


class DummyAgent:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def invoke(self, _: object) -> dict[str, object]:
        return {"output": self.payload}


def test_decide_folder_parses_json_output() -> None:
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


def test_decide_folder_falls_back_to_heuristic() -> None:
    agent = DummyAgent("not json")
    decision = decide_folder(
        agent,
        filename="receipt.txt",
        extracted_text="receipt payment",
        tree_snapshot=[],
    )
    assert decision.folder.startswith("Finance/")
