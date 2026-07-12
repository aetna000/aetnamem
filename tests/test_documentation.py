from __future__ import annotations

from pathlib import Path
import json
import re

from aetnamem import Memory
from aetnamem.mcp import MCPServer


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_FILES = (
    ROOT / "README.md",
    ROOT / "TODO.md",
    ROOT / "plan.md",
    *sorted((ROOT / "docs").glob("*.md")),
    ROOT / "bench" / "README.md",
    ROOT / "integrations" / "openclaw" / "README.md",
)


def test_documentation_structure_and_local_links() -> None:
    markdown_link = re.compile(r"\[[^]]*\]\(([^)]+)\)")
    for path in MARKDOWN_FILES:
        text = path.read_text()
        assert text.count("```") % 2 == 0, f"unbalanced code fence in {path}"
        for target in markdown_link.findall(text):
            target = target.split("#", 1)[0]
            if not target or target.startswith(("https://", "http://")):
                continue
            assert (path.parent / target).exists(), f"broken link in {path}: {target}"


def test_documented_mcp_catalog_matches_runtime() -> None:
    runtime_names = {
        tool["name"]
        for tool in MCPServer(Memory(":memory:"))._tool_definitions()
    }
    guide = (ROOT / "docs" / "integration-guide.md").read_text()
    documented_names = set(
        re.findall(r"^\| `(memory_[a-z_]+)` \|", guide, flags=re.MULTILINE)
    )
    assert documented_names == runtime_names

    readme = (ROOT / "README.md").read_text()
    for name in runtime_names:
        assert f"`{name}`" in readme


def test_integration_json_files_parse() -> None:
    integration = ROOT / "integrations" / "openclaw"
    for name in (
        "package.json",
        "package-lock.json",
        "openclaw.plugin.json",
        "tsconfig.json",
    ):
        json.loads((integration / name).read_text())
