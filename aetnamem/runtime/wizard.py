from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from aetnamem.runtime.config import PRESETS, preset_config, validate_config


def run_setup_wizard(
    *,
    preset: str,
    db_path: str,
    output_path: str,
    subject_id: str,
    agent_id: str,
    skill_paths: list[str] | None = None,
    non_interactive: bool = False,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> dict:
    """A plain-language ten-step setup usable in terminals and scripts."""

    print_fn("Step 1/10 · Welcome")
    print_fn("AetnaMem gives one agent four kinds of memory through one connection.")

    print_fn("Step 2/10 · Choose a ready-made setup")
    if not non_interactive:
        answer = input_fn(
            f"Preset ({'/'.join(PRESETS)}, default {preset}): "
        ).strip()
        if answer:
            preset = answer
    if preset not in PRESETS:
        raise ValueError(f"unknown preset: {preset}")
    print_fn(f"Using {preset}: {PRESETS[preset]['description']}")

    print_fn("Step 3/10 · Name the person whose memories these are")
    if not non_interactive:
        subject_id = input_fn(f"Memory subject (default {subject_id}): ").strip() or subject_id

    print_fn("Step 4/10 · Name the agent")
    if not non_interactive:
        agent_id = input_fn(f"Agent id (default {agent_id}): ").strip() or agent_id

    print_fn("Step 5/10 · Choose private storage")
    if not non_interactive:
        db_path = input_fn(f"SQLite file (default {db_path}): ").strip() or db_path

    print_fn("Step 6/10 · Find optional agent skills")
    paths = list(skill_paths or [])
    if not non_interactive:
        answer = input_fn("SKILL.md folder (optional, Enter to skip): ").strip()
        if answer:
            paths.append(answer)

    print_fn("Step 7/10 · Choose where the setup file lives")
    if not non_interactive:
        output_path = (
            input_fn(f"Config file (default {output_path}): ").strip() or output_path
        )

    print_fn("Step 8/10 · Confirm the safety model")
    print_fn("Working state stays agent-scoped; lessons start quarantined; skills inform but never authorize actions.")
    if not non_interactive:
        answer = input_fn("Continue? [Y/n]: ").strip().lower()
        if answer in {"n", "no"}:
            raise ValueError("setup cancelled")

    print_fn("Step 9/10 · Write and verify the configuration")
    config = preset_config(
        preset,
        db_path=str(Path(db_path).expanduser()),
        subject_id=subject_id,
        agent_id=agent_id,
        skill_paths=paths,
    )
    validate_config(config)
    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print_fn(f"Saved {output}")

    print_fn("Step 10/10 · Connect your agent")
    print_fn(f"Test it: aetnamem runtime status --config {output}")
    print_fn(f"Generic MCP: aetnamem runtime mcp --config {output}")
    print_fn(
        "OpenClaw: openclaw aetnamem setup --single-user "
        f"--subject {subject_id} --orchestrated --runtime-config {output}"
    )
    return config
