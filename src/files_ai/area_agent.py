"""Area/category creation moderation agent."""

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

from .agent import _configure_langsmith
from .johnny_decimal import JohnnyDecimalCreationAnalysis
from .tree import build_folder_snapshot_tree

AREA_CREATION_SYSTEM_PROMPT = """You moderate Johnny.Decimal area/category creation.
Return JSON only with keys:
- approved: boolean
- reasoning: short rationale
- folder: replacement Johnny.Decimal Area/Category/ID path (string or null)
- confidence: number in [0,1]
- quarantine: boolean

Rules:
1) Top-level areas are capped at 10 total: 00-09 through 90-99.
2) Never approve creating duplicate 90-99 overflow-like areas.
3) Prefer reusing an existing area/category whenever semantically compatible.
4) New areas must be broad, durable domains, never narrow one-off topics.
5) New categories should be placed inside existing broad areas when possible.
6) If no confident replacement exists and creation is not warranted, set
   quarantine=true.
7) If approved=true, folder may be null unless you want to override with a
   better existing path.
8) Do not moderate pure new-ID creation inside an existing category.
"""


class AreaAgentParseError(ValueError):
    """Raised when area moderation output cannot be parsed."""


class AreaAgentProtocol(Protocol):
    """Minimal protocol for area moderation agent usage."""

    def invoke(self, payload: dict[str, Any], **kwargs: Any) -> Any:
        """Run area moderation and return response payload."""


class AreaCreationDecision(BaseModel):
    """Area/category moderation result."""

    model_config = ConfigDict(frozen=True)

    approved: bool
    reasoning: str
    folder: str | None = None
    confidence: float
    quarantine: bool = False

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, confidence: float) -> float:
        return max(0.0, min(1.0, confidence))

    @field_validator("folder")
    @classmethod
    def _sanitize_folder(cls, folder: str | None) -> str | None:
        if folder is None:
            return None
        parts: list[str] = []
        for raw in folder.split("/"):
            clean = re.sub(r"[^a-zA-Z0-9 _.-]", "", raw).strip().strip(".")
            if clean:
                parts.append(clean)
        return "/".join(parts[:4]) or None


def build_area_creation_agent(
    *,
    settings_model: str,
    model_reasoning: bool | str | None,
    base_url: str,
    api_key: str,
) -> AreaAgentProtocol:
    """Build area/category moderation agent."""
    llm = ChatOllama(
        model=settings_model,
        reasoning=model_reasoning,
        base_url=base_url,
        client_kwargs={"headers": {"Authorization": f"Bearer {api_key}"}},
        temperature=0,
    )
    return create_agent(model=llm, tools=[], system_prompt=AREA_CREATION_SYSTEM_PROMPT)


def build_area_creation_agent_from_settings(settings: Any) -> AreaAgentProtocol:
    """Build moderation agent from runtime settings object."""
    _configure_langsmith(settings)
    return build_area_creation_agent(
        settings_model=settings.area_creation_model,
        model_reasoning=settings.model_reasoning,
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key.get_secret_value(),
    )


def moderate_area_creation(
    agent: AreaAgentProtocol,
    *,
    proposed_folder: str,
    creation: JohnnyDecimalCreationAnalysis,
    tree_snapshot: list[str],
    user_context: str,
    source_relative_dir: str = "",
    filename: str = "",
    extracted_text: str = "",
    decision_kind: str = "file",
) -> AreaCreationDecision:
    """Moderate a proposed path that would create a new area/category."""
    tree_block = build_folder_snapshot_tree(tree_snapshot)
    payload = {
        "messages": [
            {
                "role": "user",
                "content": (
                    "# Task\n"
                    "Moderate a proposed Johnny.Decimal creation decision.\n\n"
                    "## Proposal\n"
                    f"- **decision_kind**: `{decision_kind}`\n"
                    f"- **proposed_folder**: `{proposed_folder}`\n"
                    f"- **source_relative_dir**: `{source_relative_dir}`\n"
                    f"- **filename**: `{filename}`\n\n"
                    "## Creation analysis\n"
                    f"- **requires_moderation**: `{creation.requires_moderation}`\n"
                    f"- **creates_area**: `{creation.creates_area}`\n"
                    f"- **creates_category**: `{creation.creates_category}`\n"
                    f"- **area_limit_reached**: `{creation.area_limit_reached}`\n"
                    f"- **area_label**: `{creation.area_label}`\n"
                    f"- **category_label**: `{creation.category_label}`\n"
                    f"- **id_label**: `{creation.id_label}`\n\n"
                    "## Existing tree\n"
                    "```json\n"
                    f"{tree_block}\n"
                    "```\n\n"
                    "## User context\n"
                    "```markdown\n"
                    f"{user_context[:4000]}\n"
                    "```\n\n"
                    "## Extracted text (or folder evidence)\n"
                    "```text\n"
                    f"{extracted_text[:4000]}\n"
                    "```"
                ),
            }
        ]
    }
    response = _invoke_agent(
        agent,
        payload,
        metadata={
            "decision_kind": decision_kind,
            "proposed_folder": proposed_folder,
            "requires_moderation": int(creation.requires_moderation),
            "creates_area": int(creation.creates_area),
            "creates_category": int(creation.creates_category),
        },
    )
    content = _extract_content(response)
    raw = _extract_json(content)
    if raw is None:
        raise AreaAgentParseError(
            f"Area agent response did not contain JSON: {content!r}"
        )
    try:
        return AreaCreationDecision.model_validate_json(raw)
    except ValidationError as exc:
        raise AreaAgentParseError(
            f"Area agent response failed schema validation: {content!r}"
        ) from exc


def _invoke_agent(
    agent: AreaAgentProtocol,
    payload: dict[str, Any],
    metadata: dict[str, str | int],
) -> Any:
    try:
        return agent.invoke(
            payload,
            config={"tags": ["area-agent"], "metadata": metadata},
        )
    except TypeError:
        return agent.invoke(payload)


def _extract_content(response: Any) -> str:
    if isinstance(response, dict):
        if "output" in response and isinstance(response["output"], str):
            return response["output"]
        messages = response.get("messages")
        if isinstance(messages, list) and messages:
            msg = messages[-1]
            if isinstance(msg, dict):
                return str(msg.get("content", ""))
            return str(getattr(msg, "content", ""))
    return str(response)


def _extract_json(content: str) -> str | None:
    value = content.strip()
    if not value:
        return None
    try:
        json.loads(value)
        return value
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, re.DOTALL)
        if not match:
            return None
        payload = match.group(0)
        try:
            json.loads(payload)
            return payload
        except json.JSONDecodeError:
            return None
