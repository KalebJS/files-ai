"""Folder agent behavior tests."""

from __future__ import annotations

from pathlib import Path

from files_ai.folder_agent import FOLDER_SYSTEM_PROMPT
from files_ai.folder_agent import _FolderInspector
from files_ai.folder_agent import _heuristic_decision
from files_ai.folder_agent import _invoke_agent
from files_ai.folder_agent import decide_folder_action
from files_ai.storage import FileRef
from files_ai.storage import LocalFiles


def test_heuristic_moves_git_folder_without_recursing(tmp_path: Path) -> None:
    """Treat .git as non-recursive dependency-bound folder."""
    files = LocalFiles(tmp_path)
    root = FileRef("local", "/dropzone/.git")
    files.make_dir(root)

    decision = _heuristic_decision(files=files, folder_ref=root)
    assert decision is not None
    assert decision.action == "move_folder"


def test_heuristic_moves_python_project_folder(tmp_path: Path) -> None:
    """Move folders with strong dependency markers as one module."""
    files = LocalFiles(tmp_path)
    root = FileRef("local", "/dropzone/my-app")
    files.make_dir(root)
    (tmp_path / "dropzone" / "my-app" / "pyproject.toml").write_text(
        "[project]\nname='my-app'\n", encoding="utf-8"
    )
    (tmp_path / "dropzone" / "my-app" / "main.py").write_text(
        "print('ok')", encoding="utf-8"
    )

    decision = _heuristic_decision(files=files, folder_ref=root)
    assert decision is not None
    assert decision.action == "move_folder"
    assert decision.folder.startswith("Code/")


def test_heuristic_recurses_independent_documents(tmp_path: Path) -> None:
    """Recurse document-heavy folders without dependency markers."""
    files = LocalFiles(tmp_path)
    root = FileRef("local", "/dropzone/tax-docs")
    files.make_dir(root)
    for name in ("w2.pdf", "receipt.pdf", "summary.txt"):
        (tmp_path / "dropzone" / "tax-docs" / name).write_text("doc", encoding="utf-8")

    decision = _heuristic_decision(files=files, folder_ref=root)
    assert decision is not None
    assert decision.action == "recurse"


def test_heuristic_moves_code_heavy_folder_without_marker(tmp_path: Path) -> None:
    """Move code-heavy folders even without explicit manifest markers."""
    files = LocalFiles(tmp_path)
    root = FileRef("local", "/dropzone/src-pack")
    files.make_dir(root)
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / "dropzone" / "src-pack" / name).write_text(
            "print(1)", encoding="utf-8"
        )

    decision = _heuristic_decision(files=files, folder_ref=root)
    assert decision is not None
    assert decision.action == "move_folder"


def test_heuristic_returns_none_for_ambiguous_folder(tmp_path: Path) -> None:
    """Return None to allow LLM decision when signals are weak."""
    files = LocalFiles(tmp_path)
    root = FileRef("local", "/dropzone/mixed")
    files.make_dir(root)
    (tmp_path / "dropzone" / "mixed" / "notes.txt").write_text("n", encoding="utf-8")
    (tmp_path / "dropzone" / "mixed" / "script.py").write_text("p", encoding="utf-8")

    decision = _heuristic_decision(files=files, folder_ref=root)
    assert decision is None


def test_heuristic_recurses_school_financial_two_pdf_case(tmp_path: Path) -> None:
    """Recurse small document-only folders when dependency is unclear."""
    files = LocalFiles(tmp_path)
    root = FileRef("local", "/dropzone/School/Financial")
    files.make_dir(root)
    (tmp_path / "dropzone" / "School" / "Financial" / "Custom.pdf").write_text(
        "doc", encoding="utf-8"
    )
    (
        tmp_path
        / "dropzone"
        / "School"
        / "Financial"
        / "Processed Information - FAFSA on the Web - Federal Student Aid.pdf"
    ).write_text("doc", encoding="utf-8")

    decision = _heuristic_decision(files=files, folder_ref=root)
    assert decision is not None
    assert decision.action == "recurse"


def test_decide_folder_action_short_circuits_git_without_llm(tmp_path: Path) -> None:
    """Use deterministic .git rule without requiring agent LLM tools."""
    files = LocalFiles(tmp_path)
    root = FileRef("local", "/dropzone/.git")
    files.make_dir(root)

    class _NoLlm:
        pass

    decision = decide_folder_action(
        _NoLlm(),  # type: ignore[arg-type]
        files=files,
        folder_ref=root,
        tree_snapshot=[],
    )
    assert decision.action == "move_folder"


def test_folder_invoke_agent_sends_agent_specific_tags() -> None:
    """Attach LangSmith tags that identify folder-agent traces."""

    class _DummyAgent:
        def __init__(self) -> None:
            self.last_request: dict[str, object] | None = None
            self.last_config: dict[str, object] | None = None

        def invoke(self, request: object, **kwargs: object) -> dict[str, object]:
            if isinstance(request, dict):
                self.last_request = request
            config = kwargs.get("config")
            if isinstance(config, dict):
                self.last_config = config
            return {"output": "{}"}

    agent = _DummyAgent()
    payload = {"messages": [{"role": "user", "content": "test"}]}
    metadata = {"path": "/dropzone/project", "source_relative_dir": ".", "tree_size": 1}

    _invoke_agent(agent, payload, metadata)

    assert agent.last_config == {
        "tags": ["folder-agent"],
        "metadata": metadata,
    }


def test_folder_prompt_enforces_dependency_not_theme() -> None:
    """Prompt should default to recurse when only thematic similarity exists."""
    assert "If dependency is unclear, choose recurse." in FOLDER_SYSTEM_PROMPT
    assert "Not enough evidence: same theme/category" in FOLDER_SYSTEM_PROMPT
    assert "folder_name=Financial" in FOLDER_SYSTEM_PROMPT
    assert '"action":"recurse"' in FOLDER_SYSTEM_PROMPT


def test_decide_folder_action_builds_structured_markdown_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    """Send structured markdown sections in folder decision prompt."""
    files = LocalFiles(tmp_path)
    root = FileRef("local", "/dropzone/mixed")
    files.make_dir(root)
    (tmp_path / "dropzone" / "mixed" / "notes.txt").write_text("n", encoding="utf-8")

    class _RuntimeAgent:
        def __init__(self) -> None:
            self.last_request: dict[str, object] | None = None

        def invoke(self, request: object, **_: object) -> dict[str, object]:
            if isinstance(request, dict):
                self.last_request = request
            return {
                "output": (
                    '{"action":"recurse","reasoning":"independent docs",'
                    '"folder":"Unsorted","confidence":0.9,"quarantine":false}'
                )
            }

    runtime = _RuntimeAgent()
    monkeypatch.setattr("files_ai.folder_agent.create_agent", lambda **_: runtime)
    monkeypatch.setattr("files_ai.folder_agent._heuristic_decision", lambda **_: None)

    class _TestAgent:
        llm = object()

    decide_folder_action(
        _TestAgent(),  # type: ignore[arg-type]
        files=files,
        folder_ref=root,
        tree_snapshot=["10-19 Finance/10 Taxes/10.01 Taxes"],
        source_relative_dir="School",
        user_context="This archive belongs to Acme.",
    )

    assert runtime.last_request is not None
    messages = runtime.last_request["messages"]
    assert isinstance(messages, list)
    content = messages[0]["content"]
    assert "# Task" in content
    assert "## Folder metadata" in content
    assert "**folder_name**: `mixed`" in content
    assert "## Existing tree" in content
    assert '"10-19 Finance"' in content
    assert '"10 Taxes"' in content
    assert '"10.01 Taxes"' in content
    assert "## User context" in content
    assert "```markdown" in content
    assert "This archive belongs to Acme." in content


def test_list_children_renders_tree_for_nested_structure(tmp_path: Path) -> None:
    """Render nested folders in tree-style output."""
    files = LocalFiles(tmp_path)
    root = FileRef("local", "/dropzone/my-app")
    files.make_dir(root)
    files.make_dir(files.join(root, "src"))
    files.make_dir(files.join(root, "tests"))
    (tmp_path / "dropzone" / "my-app" / "pyproject.toml").write_text(
        "[project]\nname='my-app'\n", encoding="utf-8"
    )
    (tmp_path / "dropzone" / "my-app" / "src" / "main.py").write_text(
        "print('ok')", encoding="utf-8"
    )
    (tmp_path / "dropzone" / "my-app" / "tests" / "test_app.py").write_text(
        "def test_ok(): pass", encoding="utf-8"
    )

    output = _FolderInspector(files, root).list_children()
    assert output.startswith("my-app/")
    assert "pyproject.toml" in output
    assert "src/" in output
    assert "main.py" in output
    assert "tests/" in output
    assert "test_app.py" in output


def test_list_children_respects_max_depth(tmp_path: Path) -> None:
    """Do not render entries deeper than max_depth."""
    files = LocalFiles(tmp_path)
    root = FileRef("local", "/dropzone/nested")
    files.make_dir(root)
    files.make_dir(files.join(root, "a"))
    files.make_dir(files.join(root, "a", "b"))
    (tmp_path / "dropzone" / "nested" / "a" / "b" / "deep.txt").write_text(
        "x", encoding="utf-8"
    )

    output = _FolderInspector(files, root).list_children(max_depth=2)
    assert "a/" in output
    assert "b/" in output
    assert "deep.txt" not in output


def test_list_children_does_not_expand_git(tmp_path: Path) -> None:
    """Show .git but do not recurse into its contents."""
    files = LocalFiles(tmp_path)
    root = FileRef("local", "/dropzone/repo")
    files.make_dir(root)
    files.make_dir(files.join(root, ".git"))
    (tmp_path / "dropzone" / "repo" / ".git" / "config").write_text(
        "[core]", encoding="utf-8"
    )

    output = _FolderInspector(files, root).list_children()
    assert ".git/" in output
    assert "config" not in output


def test_list_children_marks_truncation(tmp_path: Path) -> None:
    """Include truncation marker when max_entries is reached."""
    files = LocalFiles(tmp_path)
    root = FileRef("local", "/dropzone/docs")
    files.make_dir(root)
    for index in range(3):
        (tmp_path / "dropzone" / "docs" / f"f{index}.txt").write_text(
            "x", encoding="utf-8"
        )

    output = _FolderInspector(files, root).list_children(max_entries=2)
    assert "...truncated..." in output
