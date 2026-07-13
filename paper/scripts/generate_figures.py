#!/usr/bin/env python3
"""Generate publication figures from pinned CSV/JSON evidence."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FIGURES = ROOT / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

INK = "#17252a"
ACCENT = "#b23a48"
TEAL = "#2a6f73"
GOLD = "#d49a2a"
PALE = "#dbe4e6"
GRID = "#c8d1d3"

DISPLAY_NAMES = {
    "aetnamem": "aetnamem",
    "agno_memory": "Agno Memory",
    "aws_bedrock_agentcore_memory": "AWS AgentCore",
    "crewai_memory": "CrewAI Memory",
    "google_adk_memory_bank": "Google ADK Memory Bank",
    "hindsight": "Hindsight",
    "langgraph": "LangGraph",
    "langmem": "LangMem",
    "llamaindex_memory": "LlamaIndex Memory",
    "supermemory": "Supermemory",
    "tree-ring-memory": "Tree Ring Memory",
    "zep": "Zep Cloud",
    "autogen_mem0memory": "AutoGen + Mem0",
    "mem0": "Mem0",
    "cognee": "Cognee",
    "letta": "Letta",
    "openai_agents_sdk_sessions": "OpenAI Agents Sessions",
    "tencentdb-agent-memory": "TencentDB Agent Memory",
    "graphiti": "Graphiti + Neo4j",
}


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def configure() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.2,
            "axes.titlesize": 10,
            "axes.labelsize": 8.5,
            "axes.edgecolor": INK,
            "axes.labelcolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "text.color": INK,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save(fig: plt.Figure, stem: str) -> None:
    fig.savefig(FIGURES / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(FIGURES / f"{stem}.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def benchmark_scores(rows: list[dict[str, str]]) -> None:
    names = [DISPLAY_NAMES[row["framework"]] for row in rows]
    checks = [100 * int(row["checks_passed"]) / int(row["checks_total"]) for row in rows]
    scenarios = [100 * int(row["scenarios_passed"]) / int(row["scenarios_total"]) for row in rows]
    y = np.arange(len(rows))
    colors = [ACCENT if row["framework"] == "aetnamem" else (TEAL if value == 100 else GOLD) for row, value in zip(rows, checks)]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.4, 7.2), gridspec_kw={"width_ratios": [1.25, 1]})
    ax1.barh(y, checks, color=colors, height=0.72)
    ax2.barh(y, scenarios, color=colors, height=0.72)
    ax1.set_yticks(y, names)
    ax2.set_yticks(y, [""] * len(rows))
    ax1.invert_yaxis()
    ax2.invert_yaxis()
    for ax, title in ((ax1, "Check-level conformance"), (ax2, "Scenario-level conformance")):
        ax.set_xlim(0, 108)
        ax.set_xlabel("Pass rate (%)")
        ax.set_title(title, loc="left", fontweight="bold")
        ax.grid(axis="x", color=GRID, linewidth=0.55, alpha=0.75)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
    for i, row in enumerate(rows):
        ax1.text(checks[i] + 1.0, i, f'{row["checks_passed"]}/{row["checks_total"]}', va="center", fontsize=7.2)
        ax2.text(scenarios[i] + 1.0, i, f'{row["scenarios_passed"]}/{row["scenarios_total"]}', va="center", fontsize=7.2)
    fig.suptitle("MemoryStackBench seven_sins_v0_1 public snapshot", x=0.07, ha="left", fontsize=12, fontweight="bold")
    fig.subplots_adjust(wspace=0.08, left=0.27, right=0.98, top=0.91, bottom=0.08)
    save(fig, "benchmark-scores")


def benchmark_matrix(rows: list[dict[str, str]]) -> None:
    columns = [
        ("write_correctness", 5, "Write\ncorrectness"),
        ("retrieval_correctness", 6, "Retrieval\ncorrectness"),
        ("deletion_behavior", 5, "Deletion\nbehavior"),
        ("untrusted_source_resistance", 10, "Untrusted-source\nresistance"),
        ("temporal_update_handling", 7, "Temporal-update\nhandling"),
    ]
    matrix = np.array([[int(row[key]) / total for key, total, _ in columns] for row in rows])
    cmap = LinearSegmentedColormap.from_list("aetna", ["#f2dfd5", "#e8b44a", "#4a9a96", "#145f64"])
    fig, ax = plt.subplots(figsize=(8.9, 7.2))
    image = ax.imshow(matrix, vmin=0, vmax=1, cmap=cmap, aspect="auto")
    ax.set_yticks(np.arange(len(rows)), [DISPLAY_NAMES[row["framework"]] for row in rows])
    ax.set_xticks(np.arange(len(columns)), [label for _, _, label in columns])
    ax.tick_params(axis="x", top=True, labeltop=True, bottom=False, labelbottom=False, pad=7)
    for i, row in enumerate(rows):
        for j, (key, total, _) in enumerate(columns):
            passed = int(row[key])
            color = "white" if passed / total >= 0.82 else INK
            ax.text(j, i, f"{passed}/{total}", ha="center", va="center", color=color, fontsize=7.4, fontweight="bold" if i == 0 else "normal")
    ax.add_patch(plt.Rectangle((-0.49, -0.49), len(columns) - 0.02, 0.98, fill=False, edgecolor=ACCENT, linewidth=2.2))
    ax.set_title("Category-level check coverage", loc="left", fontsize=12, fontweight="bold", pad=13)
    for spine in ax.spines.values():
        spine.set_visible(False)
    colorbar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.025)
    colorbar.set_label("Pass fraction")
    fig.subplots_adjust(left=0.31, right=0.92, top=0.84, bottom=0.04)
    save(fig, "benchmark-matrix")


def auditability(rows: list[dict[str, str]]) -> None:
    rows = sorted(rows, key=lambda row: (-int(row["points"]), row["framework"] != "aetnamem", DISPLAY_NAMES[row["framework"]]))
    names = [DISPLAY_NAMES[row["framework"]] for row in rows]
    points = [int(row["points"]) for row in rows]
    y = np.arange(len(rows))
    colors = [ACCENT if row["framework"] == "aetnamem" else PALE for row in rows]
    edges = [ACCENT if row["framework"] == "aetnamem" else TEAL for row in rows]
    fig, ax = plt.subplots(figsize=(8.7, 7.0))
    ax.barh(y, points, color=colors, edgecolor=edges, linewidth=0.9, height=0.72)
    ax.set_yticks(y, names)
    ax.invert_yaxis()
    ax.set_xlim(0, 18.9)
    ax.set_xticks(np.arange(0, 19, 3))
    ax.set_xlabel("Auditability evidence points (maximum 18)")
    ax.set_title("MemoryStackBench auditability matrix", loc="left", fontsize=12, fontweight="bold")
    ax.grid(axis="x", color=GRID, linewidth=0.55)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    for i, row in enumerate(rows):
        label = "native declaration" if row["origin"] == "native" else "undeclared origin"
        ax.text(points[i] + 0.2, i, f'{points[i]}/18  {label}', va="center", fontsize=7.1, color=ACCENT if i == 0 else INK)
    fig.subplots_adjust(left=0.31, right=0.96, top=0.92, bottom=0.09)
    save(fig, "auditability")


def aetnamem_profile(benchmark: list[dict[str, str]], audits: list[dict[str, str]]) -> None:
    row = next(item for item in benchmark if item["framework"] == "aetnamem")
    audit = next(item for item in audits if item["framework"] == "aetnamem")
    safety = [
        ("Write", int(row["write_correctness"]), 5),
        ("Retrieval", int(row["retrieval_correctness"]), 6),
        ("Deletion", int(row["deletion_behavior"]), 5),
        ("Untrusted source", int(row["untrusted_source_resistance"]), 10),
        ("Temporal update", int(row["temporal_update_handling"]), 7),
    ]
    evidence = [
        ("Inspectability", int(audit["inspectability"]), 3),
        ("Provenance", int(audit["provenance"]), 3),
        ("Retrieval trace", int(audit["retrieval_transparency"]), 3),
        ("Deletion evidence", int(audit["deletion_evidence"]), 3),
        ("Mutation lineage", int(audit["mutation_lineage"]), 3),
        ("Tamper evidence", int(audit["tamper_evidence"]), 3),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 3.6), gridspec_kw={"width_ratios": [1, 1.2]})
    for ax, values, title, color in (
        (axes[0], safety, "Safety conformance", TEAL),
        (axes[1], evidence, "Auditability evidence", ACCENT),
    ):
        x = np.arange(len(values))
        fractions = [passed / total for _, passed, total in values]
        ax.bar(x, fractions, color=color, width=0.67)
        ax.set_ylim(0, 1.13)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1], ["0", "25", "50", "75", "100"])
        ax.set_ylabel("Percent of available points")
        ax.set_xticks(x, [name for name, _, _ in values], rotation=28, ha="right")
        ax.set_title(title, loc="left", fontweight="bold")
        ax.grid(axis="y", color=GRID, linewidth=0.55)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
        for i, (_, passed, total) in enumerate(values):
            ax.text(i, fractions[i] + 0.025, f"{passed}/{total}", ha="center", fontsize=7.5, fontweight="bold")
    fig.suptitle("aetnamem evaluation profile", x=0.06, ha="left", fontsize=12, fontweight="bold")
    fig.subplots_adjust(wspace=0.3, left=0.08, right=0.98, top=0.82, bottom=0.3)
    save(fig, "aetnamem-profile")


def demo_trace() -> None:
    events = [
        ("Trusted fact", "accepted"),
        ("Web poison", "quarantined"),
        ("Recall", "trusted only"),
        ("Untrusted authority", "refused"),
        ("Missing authority", "refused"),
        ("No reviewer key", "refused"),
        ("Unapproved plan", "refused"),
        ("Exact-plan approval", "committed"),
        ("Plan mutation", "detected"),
        ("History mutation", "detected"),
    ]
    palette = {
        "accepted": TEAL,
        "quarantined": GOLD,
        "trusted only": TEAL,
        "refused": ACCENT,
        "committed": "#397a4a",
        "detected": "#6b4c9a",
    }
    markers = {"accepted": "o", "quarantined": "D", "trusted only": "o", "refused": "X", "committed": "s", "detected": "P"}
    fig, ax = plt.subplots(figsize=(10.4, 3.2))
    x = np.arange(1, len(events) + 1)
    ax.plot(x, np.zeros_like(x), color=GRID, linewidth=2.0, zorder=1)
    for i, (label, outcome) in enumerate(events, start=1):
        ax.scatter(i, 0, s=110, marker=markers[outcome], color=palette[outcome], edgecolor="white", linewidth=0.8, zorder=3)
        above = i % 2 == 1
        y = 0.48 if above else -0.48
        ax.plot([i, i], [0.08 if above else -0.08, y * 0.68], color=GRID, linewidth=0.8)
        ax.text(i, y, label, ha="center", va="center", fontsize=7.2, fontweight="bold")
        ax.text(i, y - (0.15 if above else -0.15), outcome, ha="center", va="center", fontsize=6.8, color=palette[outcome])
    ax.set_xlim(0.4, len(events) + 0.6)
    ax.set_ylim(-0.78, 0.78)
    ax.axis("off")
    ax.set_title("Flagship demo: observed control decisions in execution order", loc="left", fontsize=12, fontweight="bold")
    fig.subplots_adjust(left=0.03, right=0.99, top=0.82, bottom=0.04)
    save(fig, "demo-trace")


def main() -> None:
    configure()
    benchmark = read_csv("benchmark-results.csv")
    audits = read_csv("auditability.csv")
    benchmark_scores(benchmark)
    benchmark_matrix(benchmark)
    auditability(audits)
    aetnamem_profile(benchmark, audits)
    demo_trace()


if __name__ == "__main__":
    main()
