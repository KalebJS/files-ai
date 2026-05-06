"""LLM agent wiring and folder-decision helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain_ollama import ChatOllama

from .config import Settings

SYSTEM_PROMPT = """You are an AI file organizer.
Return JSON only with keys:
- folder: target folder under organized root
- reasoning: short rationale
- confidence: number in [0,1]
- quarantine: boolean
Keep folder depth <= 4.
"""


@dataclass(frozen=True)
class AgentDecision:
    """Structured folder-routing decision."""

    folder: str
    reasoning: str
    confidence: float
    quarantine: bool = False


def build_agent(settings: Settings) -> Any:
    """Create a LangChain agent backed by ChatOllama."""
    llm = ChatOllama(
        model=settings.model,
        base_url=settings.ollama_base_url,
        client_kwargs={
            "headers": {
                "Authorization": f"Bearer {settings.ollama_api_key.get_secret_value()}"
            }
        },
        temperature=0,
    )
    return create_agent(model=llm, tools=[], system_prompt=SYSTEM_PROMPT)


def decide_folder(
    agent: Any, *, filename: str, extracted_text: str, tree_snapshot: list[str]
) -> AgentDecision:
    """Ask the agent for a folder decision and normalize output."""
    prompt = (
        "Choose folder for file.\n"
        f"filename={filename}\n"
        f"tree={tree_snapshot}\n"
        f"text={extracted_text[:4000]}"
    )
    response = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    content = _extract_content(response)
    parsed = _parse_json(content)
    if parsed is None:
        return _heuristic_decision(filename, extracted_text)
    folder = str(parsed.get("folder") or "Unsorted")
    reasoning = str(parsed.get("reasoning") or "model decision")
    confidence = float(parsed.get("confidence") or 0.4)
    quarantine = bool(parsed.get("quarantine") or False)
    return AgentDecision(
        folder=_sanitize_folder(folder),
        reasoning=reasoning,
        confidence=max(0.0, min(1.0, confidence)),
        quarantine=quarantine,
    )


def _extract_content(response: Any) -> str:
    """Extract assistant text content from agent responses."""
    if isinstance(response, dict):
        if "output" in response and isinstance(response["output"], str):
            return response["output"]
        messages = response.get("messages")
        if isinstance(messages, list) and messages:
            msg = messages[-1]
            if isinstance(msg, dict):
                return str(msg.get("content", ""))
            content = getattr(msg, "content", "")
            return str(content)
    return str(response)


def _parse_json(content: str) -> dict[str, Any] | None:
    """Parse JSON content, including fenced or mixed outputs."""
    content = content.strip()
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _heuristic_decision(filename: str, extracted_text: str) -> AgentDecision:
    """Return fallback folder decision from simple keyword matching."""
    corpus = f"{filename} {extracted_text}".lower()
    pairs = [
        ("invoice", "Finance/Invoices"),
        ("receipt", "Finance/Receipts"),
        ("tax", "Finance/Taxes"),
        ("resume", "Career/Resumes"),
        ("photo", "Media/Photos"),
        ("screenshot", "Media/Screenshots"),
        ("contract", "Legal/Contracts"),
        ("code", "Code/Misc"),
    ]
    for token, folder in pairs:
        if token in corpus:
            return AgentDecision(
                folder=folder, reasoning=f"matched {token}", confidence=0.65
            )
    return AgentDecision(
        folder="Unsorted", reasoning="no strong signal", confidence=0.3
    )


def _sanitize_folder(folder: str) -> str:
    """Normalize model folder output into safe path segments."""
    parts: list[str] = []
    for raw in folder.split("/"):
        clean = re.sub(r"[^a-zA-Z0-9 _.-]", "", raw).strip().strip(".")
        if clean:
            parts.append(clean)
    return "/".join(parts[:4]) or "Unsorted"
