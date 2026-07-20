"""Deterministic, dependency-free EtD Markdown reporting."""

from __future__ import annotations

from typing import Any


def render_markdown(bundle: dict[str, Any]) -> str:
    case = bundle["case"]
    lines = [
        f"# {case['title']}",
        "",
        f"Decision case: `{case['id']}`  ",
        f"Status: **{case['status']}**  ",
        f"Template: `{case['template_id']}@{case['template_version']}`  ",
        f"Bundle digest: `{bundle.get('bundle_digest', '')}`",
        "",
        "## Question and scope",
        "",
    ]
    for key, value in sorted((case.get("content") or {}).items()):
        lines.append(f"- **{key.replace('_', ' ').title()}:** {_display(value)}")

    revisions = bundle.get("revisions", [])
    assessments = [row for row in revisions if row.get("kind") == "criterion_assessment"]
    lines.extend(["", "## Criterion assessments", ""])
    if not assessments:
        lines.append("No criterion assessments have been recorded.")
    for assessment in assessments:
        content = assessment["content"]
        lines.extend(
            [
                f"### {str(content.get('criterion', 'criterion')).replace('_', ' ').title()}",
                "",
                f"Judgment: **{content.get('judgment', 'not recorded')}**  ",
                f"Rationale: {_display(content.get('rationale', ''))}",
            ]
        )
        ratings = content.get("ratings") or []
        if ratings:
            lines.append("Ratings: " + ", ".join(f"{item.get('scheme')}: {item.get('value')}" for item in ratings))
        if assessment.get("links"):
            lines.append("Evidence revisions: " + ", ".join(f"`{item['source_revision_id']}` ({item['role']})" for item in assessment["links"]))
        lines.append("")

    recommendations = [row for row in revisions if row.get("kind") == "recommendation"]
    lines.extend(["## Recommendations", ""])
    if not recommendations:
        lines.append("No recommendation has been recorded.")
    for recommendation in recommendations:
        content = recommendation["content"]
        lines.extend(
            [
                f"### Revision {recommendation['revision']}",
                "",
                str(content.get("text", "")),
                "",
                f"Direction: **{content.get('direction', 'not recorded')}**  ",
                f"Strength: **{content.get('strength', 'not recorded')}**  ",
                f"Justification: {_display(content.get('justification', ''))}",
                "",
            ]
        )

    lines.extend(["## Deliberation and authorization", ""])
    for ballot in bundle.get("ballots", []):
        outcome = ballot.get("outcome")
        result = outcome["outcome"] if outcome else None
        lines.append(
            f"- Ballot `{ballot['id']}`: **{ballot['state']}**"
            + (f", passed={result['passed']}, quorum={result['quorum_met']}" if result else "")
        )
    for adoption in bundle.get("adoptions", []):
        lines.append(f"- Adoption `{adoption['id']}` binds revision `{adoption['target_revision_id']}`.")
    for authorization in bundle.get("authorizations", []):
        lines.append(
            f"- Authorization `{authorization['id']}` is **{authorization['status']}** for plan `{authorization['plan_revision_id']}`."
        )

    lines.extend(
        [
            "",
            "## Assurance boundary",
            "",
            "This report records an evidence-linked workflow. The host authenticates participants and remains responsible for methodology, regulatory obligations, and implementation governance.",
            "",
        ]
    )
    return "\n".join(lines)


def _display(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_display(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}={_display(item)}" for key, item in sorted(value.items()))
    return str(value)

