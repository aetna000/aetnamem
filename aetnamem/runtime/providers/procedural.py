from __future__ import annotations

from pathlib import Path
import re

from aetnamem.core.canonical import sha256_hex
from aetnamem.runtime.models import (
    OutcomeReport,
    PlaneContribution,
    ProviderHealth,
    TurnRequest,
)
from aetnamem.runtime.store import RuntimeStore


class ProceduralProvider:
    plane = "procedural"

    def __init__(
        self,
        store: RuntimeStore,
        *,
        skill_paths: list[str] | None = None,
        max_chars: int = 800,
        max_skills: int = 2,
    ) -> None:
        self.store = store
        self.skill_paths = [Path(value).expanduser() for value in (skill_paths or [])]
        self.max_chars = max(0, int(max_chars))
        self.max_skills = max(0, int(max_skills))

    def prepare(self, request: TurnRequest) -> PlaneContribution:
        query_terms = _terms(request.query)
        candidates: list[tuple[int, dict]] = []
        for skill_file in self._skill_files():
            try:
                content = skill_file.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            name, description = _metadata(skill_file, content)
            score = len(query_terms & _terms(f"{name} {description}"))
            if query_terms and score == 0:
                continue
            stored = self.store.upsert_procedure(
                source_path=str(skill_file),
                name=name,
                description=description,
                content=content,
                digest=sha256_hex(content),
            )
            candidates.append((score, stored))
        candidates.sort(key=lambda pair: (pair[0], pair[1]["name"]), reverse=True)

        lines = ["<procedural_memory>"]
        item_ids: list[str] = []
        provenance: list[dict] = []
        selected: list[dict] = []
        for _, procedure in candidates[: self.max_skills]:
            excerpt = _body_excerpt(str(procedure["content"]), 320)
            line = (
                f"- Use procedure {procedure['name']}: {procedure['description']} "
                f"[procedure:{procedure['version_id'][:16]}]\n  {excerpt}"
            )
            if sum(len(item) + 1 for item in lines) + len(line) + 22 > self.max_chars:
                break
            lines.append(line)
            item_ids.append(str(procedure["version_id"]))
            provenance.append(
                {
                    "kind": "procedure_version",
                    "id": procedure["version_id"],
                    "source_path": procedure["source_path"],
                    "relation": "informed_by",
                }
            )
            selected.append(
                {
                    "name": procedure["name"],
                    "version_id": procedure["version_id"],
                    "content_sha256": procedure["content_sha256"],
                }
            )
        lines.append("</procedural_memory>")
        content = "\n".join(lines) if len(lines) > 2 else ""
        return PlaneContribution(
            plane=self.plane,
            content=content,
            item_ids=item_ids,
            provenance=provenance,
            metadata={
                "selected": selected,
                "authorization": "none; procedures only inform host-authorized actions",
            },
            placement="stable_system_prefix",
            trust="versioned_procedure",
        )

    def record_outcome(self, outcome: OutcomeReport) -> list[dict]:
        proposals: list[dict] = []
        for version_id in self.store.procedure_versions_for_run(outcome.run_id):
            self.store.record_procedure_evaluation(
                procedure_version_id=version_id,
                run_id=outcome.run_id,
                success=outcome.success,
            )
            if not outcome.success:
                proposals.append(
                    self.store.create_procedure_improvement(
                        procedure_version_id=version_id,
                        run_id=outcome.run_id,
                    )
                )
        return proposals

    def health(self) -> ProviderHealth:
        missing = [str(path) for path in self.skill_paths if not path.exists()]
        detail = "ready" if not missing else f"missing optional paths: {', '.join(missing)}"
        return ProviderHealth(self.plane, True, detail)

    def _skill_files(self) -> list[Path]:
        files: list[Path] = []
        for path in self.skill_paths:
            if path.is_file() and path.name == "SKILL.md":
                files.append(path)
            elif path.is_dir():
                files.extend(path.glob("SKILL.md"))
                files.extend(path.glob("*/SKILL.md"))
        return sorted(set(files))


def _terms(value: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z0-9_-]+", value.lower())
        if len(term) >= 3
    }


def _metadata(path: Path, content: str) -> tuple[str, str]:
    name = path.parent.name or "procedure"
    description = ""
    frontmatter = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if frontmatter:
        for line in frontmatter.group(1).splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "name" and value.strip():
                name = value.strip().strip("\"'")
            elif key.strip() == "description" and value.strip():
                description = value.strip().strip("\"'")
    if not description:
        for line in content.splitlines():
            text = line.strip().lstrip("#").strip()
            if text and text != "---" and not text.startswith(("name:", "description:")):
                description = text
                break
    return name, description[:240]


def _body_excerpt(content: str, max_chars: int) -> str:
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL)
    compact = " ".join(body.split())
    return compact[:max_chars]
