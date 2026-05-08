"""LLM agent wiring and folder-decision helpers."""

from __future__ import annotations

import json
import re
from typing import Any
from typing import Protocol

from langchain.agents import create_agent
from langchain_ollama import ChatOllama
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import ValidationError
from pydantic import field_validator

from .config import Settings

SYSTEM_PROMPT = """You are an AI file organizer.
Return JSON only with keys:
- reasoning: short rationale
- folder: target folder under organized root
- confidence: number in [0,1]
- quarantine: boolean
Keep folder depth <= 4.

Examples:
Input:
filename=invoice_2026_april.pdf
tree=['Finance/Invoices', 'Finance/Receipts', 'Legal/Contracts']
text=Invoice #1042 due on 2026-05-15 for consulting services.
Output:
{"reasoning":"invoice terms and due date",
"folder":"Finance/Invoices","confidence":0.93,"quarantine":false}

Input:
filename=beach_trip.jpg
tree=['Media/Photos', 'Media/Screenshots']
text=Photo from summer vacation at the beach.
Output:
{"reasoning":"photo content and filename",
"folder":"Media/Photos","confidence":0.84,"quarantine":false}

Input:
filename=unknown.bin
tree=['Code/Misc', 'Unsorted']
text=Binary blob with unreadable or ambiguous content.
Output:
{"reasoning":"insufficient semantic signal",
"folder":"Unsorted","confidence":0.31,"quarantine":false}
"""


class AgentParseError(ValueError):
    """Raised when the agent output cannot be parsed into a valid decision."""


class AgentProtocol(Protocol):
    """Minimal protocol for agent usage in this project."""

    def invoke(self, payload: dict[str, Any]) -> Any:
        """Run the agent and return a response payload."""


class AgentDecision(BaseModel):
    """Structured folder-routing decision.

    Attributes:
        folder: Target relative folder under organized root.
        reasoning: Short rationale for the route.
        confidence: Confidence score in `[0, 1]`.
        quarantine: Whether the file should be quarantined.
    """

    model_config = ConfigDict(frozen=True)

    folder: str = "Unsorted"
    reasoning: str
    confidence: float
    quarantine: bool = False

    @field_validator("folder")
    @classmethod
    def _sanitize_folder(cls, folder: str) -> str:
        """Normalize model folder output into safe path segments."""
        parts: list[str] = []
        for raw in folder.split("/"):
            clean = re.sub(r"[^a-zA-Z0-9 _.-]", "", raw).strip().strip(".")
            if clean:
                parts.append(clean)
        return "/".join(parts[:4]) or "Unsorted"

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, confidence: float) -> float:
        """Clamp confidence to a valid probability interval."""
        return max(0.0, min(1.0, confidence))


def build_agent(settings: Settings) -> AgentProtocol:
    """Create a LangChain agent backed by ChatOllama.

    Args:
        settings: Runtime settings containing model and API config.

    Returns:
        AgentProtocol: Agent object compatible with `.invoke(...)`.
    """
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
    agent: AgentProtocol,
    *,
    filename: str,
    extracted_text: str,
    tree_snapshot: list[str],
) -> AgentDecision:
    """Ask the agent for a folder decision and normalize output.

    Args:
        agent: Agent instance with an `invoke` method.
        filename: Source filename.
        extracted_text: Extracted file text used for routing.
        tree_snapshot: Existing organized folder paths for context.

    Returns:
        AgentDecision: Normalized routing decision.
    """
    prompt = (
        "Choose folder for file.\n"
        f"filename={filename}\n"
        f"tree={tree_snapshot}\n"
        f"text={extracted_text[:4000]}"
    )
    response = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    content = _extract_content(response)
    payload = _extract_json_str(content)
    if payload is None:
        raise AgentParseError(f"Agent response did not contain JSON: {content!r}")
    try:
        return AgentDecision.model_validate_json(payload)
    except ValidationError as exc:
        raise AgentParseError(
            f"Agent response failed schema validation: {content!r}"
        ) from exc


def _extract_content(response: Any) -> str:
    """Extract assistant text content from agent responses.

    Args:
        response: Agent response payload in dict or message-like form.

    Returns:
        str: Best-effort text content from the response.
    """
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


def _extract_json_str(content: str) -> str | None:
    """Extract JSON object string from raw model output.

    Args:
        content: Raw model output.

    Returns:
        str | None: JSON object string when available.
    """
    content = content.strip()
    if not content:
        return None
    try:
        json.loads(content)
        return content
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return None
        try:
            payload = match.group(0)
            json.loads(payload)
            return payload
        except json.JSONDecodeError:
            return None
