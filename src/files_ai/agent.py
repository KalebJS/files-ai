"""LLM agent wiring and folder-decision helpers."""

from __future__ import annotations

import json
import os
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

SYSTEM_PROMPT = """You are an AI file organizer for a personal/work archive.
Return JSON only with keys:
- reasoning: short rationale
- folder: target folder under organized root
- confidence: number in [0,1]
- quarantine: boolean

Hard rules:
1) Keep folder depth <= 4 and use safe names.
2) Prefer a specific semantic destination, not generic catch-all bins.
3) Use an existing folder from tree only when it is clearly the best fit.
4) If no existing folder fits, create a concise new folder path based on content.
5) "Unsorted" is a last-resort failure bucket and should almost never be chosen.
6) Only set quarantine=true for unsafe, suspicious, or policy-sensitive content.

Folder strategy:
- First classify by strongest evidence from filename, source_relative_dir, and text.
- Reuse existing paths when strongly compatible.
- Otherwise create a new path like:
  - Academics/Coursework
  - Code/C++
  - Legal/Housing
  - Media/Photos
  - Finance/Statements

Examples:
Input:
filename=invoice_2026_april.pdf
source_relative_dir=
tree=['Finance/Invoices', 'Finance/Receipts', 'Legal/Contracts']
text=Invoice #1042 due on 2026-05-15 for consulting services.
Output:
{"reasoning":"invoice terms and due date","folder":"Finance/Invoices",
"confidence":0.93,"quarantine":false}

Input:
filename=Lab8.cpp
source_relative_dir=Security
tree=['Unsorted']
text=C++ assignment implementing data structures and traversal.
Output:
{"reasoning":"coursework source code signals C++ category","folder":"Code/C++",
"confidence":0.88,"quarantine":false}

Input:
filename=Working_with_Real_Estate_Agents_Disclosure.pdf
source_relative_dir=Legal
tree=['Unsorted', 'Legal']
text=Buyer disclosure and agency agreement terms.
Output:
{"reasoning":"real-estate legal document","folder":"Legal/Housing",
"confidence":0.9,"quarantine":false}
"""


class AgentParseError(ValueError):
    """Raised when the agent output cannot be parsed into a valid decision."""


class AgentProtocol(Protocol):
    """Minimal protocol for agent usage in this project."""

    def invoke(self, payload: dict[str, Any], **kwargs: Any) -> Any:
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
    _configure_langsmith(settings)
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
    source_relative_dir: str = "",
) -> AgentDecision:
    """Ask the agent for a folder decision and normalize output.

    Args:
        agent: Agent instance with an `invoke` method.
        filename: Source filename.
        extracted_text: Extracted file text used for routing.
        tree_snapshot: Existing organized folder paths for context.
        source_relative_dir: Dropzone-relative source folder context.

    Returns:
        AgentDecision: Normalized routing decision.
    """
    prompt = _build_prompt(
        filename=filename,
        extracted_text=extracted_text,
        tree_snapshot=tree_snapshot,
        source_relative_dir=source_relative_dir,
    )
    payload = {"messages": [{"role": "user", "content": prompt}]}
    response = _invoke_agent(
        agent,
        payload,
        metadata={
            "filename": filename,
            "source_relative_dir": source_relative_dir or ".",
            "tree_size": len(tree_snapshot),
        },
    )
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


def _configure_langsmith(settings: Settings) -> None:
    """Configure LangSmith tracing environment for LangChain runtime."""
    if not settings.langsmith_tracing:
        os.environ["LANGSMITH_TRACING"] = "false"
        return
    os.environ["LANGSMITH_TRACING"] = "true"
    key = settings.langsmith_api_key.get_secret_value()
    if key:
        os.environ["LANGSMITH_API_KEY"] = key
    if settings.langsmith_project:
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint


def _build_prompt(
    *,
    filename: str,
    extracted_text: str,
    tree_snapshot: list[str],
    source_relative_dir: str,
) -> str:
    """Build a routing prompt with stronger anti-Unsorted guidance."""
    filtered_tree = [folder for folder in tree_snapshot if folder != "Unsorted"]
    unsorted_present = len(filtered_tree) != len(tree_snapshot)
    return (
        "Choose folder for file.\n"
        "Decision policy:\n"
        "- Favor specific semantic categories.\n"
        "- Reuse an existing folder only when strongly correct.\n"
        "- If none fit, create a new concise folder path.\n"
        "- Avoid Unsorted except as a true last resort.\n"
        f"filename={filename}\n"
        f"source_relative_dir={source_relative_dir}\n"
        f"tree={filtered_tree}\n"
        f"unsorted_present={unsorted_present}\n"
        f"text={extracted_text[:4000]}"
    )


def _invoke_agent(
    agent: AgentProtocol,
    payload: dict[str, Any],
    metadata: dict[str, str | int],
) -> Any:
    """Invoke agent with optional trace metadata when supported."""
    try:
        return agent.invoke(
            payload,
            config={
                "tags": ["file-agent"],
                "metadata": metadata,
            },
        )
    except TypeError:
        return agent.invoke(payload)


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
