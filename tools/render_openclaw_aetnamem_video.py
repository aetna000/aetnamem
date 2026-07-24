#!/usr/bin/env python3
from __future__ import annotations

import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/assets/demos/openclaw-aetnamem-side-by-side.mp4"
WIDTH, HEIGHT = 1920, 1080
FPS = 30

FONT_REGULAR = "/System/Library/Fonts/SFNS.ttf"
FONT_BOLD = "/System/Library/Fonts/SFNS.ttf"
FONT_MONO = "/System/Library/Fonts/SFNSMono.ttf"

INK = "#10242b"
MUTED = "#60747b"
TEAL = "#00aeb3"
TEAL_DARK = "#08747a"
CYAN = "#54dbe0"
BLUE = "#315a7d"
RED = "#d94a4a"
GOLD = "#f2a51a"
PANEL = "#ffffff"
PANEL_ALT = "#f3f8f9"
LINE = "#d8e5e8"


def font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_MONO if mono else FONT_BOLD if bold else FONT_REGULAR
    return ImageFont.truetype(path, size)


def gradient_background() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()
    top = (247, 251, 252)
    bottom = (225, 240, 242)
    for y in range(HEIGHT):
        ratio = y / (HEIGHT - 1)
        row = tuple(round(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        for x in range(WIDTH):
            glow = max(0.0, 1.0 - math.dist((x, y), (1520, 120)) / 1150)
            pixels[x, y] = tuple(min(255, round(value + glow * 10)) for value in row)
    return image


def text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    size: int,
    fill: str = INK,
    *,
    bold: bool = False,
    mono: bool = False,
    anchor: str | None = None,
) -> None:
    draw.text(xy, value, font=font(size, bold=bold, mono=mono), fill=fill, anchor=anchor)


def wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    size: int,
    width: int,
    fill: str = INK,
    *,
    bold: bool = False,
    spacing: int = 10,
) -> int:
    chars = max(12, int(width / (size * 0.54)))
    lines = textwrap.wrap(value, width=chars)
    y = xy[1]
    for line in lines:
        text(draw, (xy[0], y), line, size, fill, bold=bold)
        y += size + spacing
    return y


def rounded_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: str = PANEL,
    outline: str = LINE,
    radius: int = 30,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def header(draw: ImageDraw.ImageDraw, kicker: str, title_value: str, subtitle: str = "") -> None:
    text(draw, (96, 62), kicker.upper(), 28, TEAL_DARK, bold=True)
    text(draw, (96, 108), title_value, 66, INK, bold=True)
    if subtitle:
        text(draw, (98, 194), subtitle, 31, MUTED)
    draw.line((96, 245, 1824, 245), fill=LINE, width=2)


def footer(draw: ImageDraw.ImageDraw, slide_number: int) -> None:
    text(draw, (96, 1030), "aetnamem · evidence before effect", 23, TEAL_DARK)
    text(draw, (1824, 1030), f"{slide_number}/9", 23, MUTED, anchor="ra")


def pill(draw: ImageDraw.ImageDraw, x: int, y: int, value: str, color: str = TEAL_DARK) -> int:
    box = draw.textbbox((0, 0), value, font=font(24, bold=True))
    width = box[2] - box[0] + 34
    draw.rounded_rectangle((x, y, x + width, y + 44), radius=22, fill=color)
    text(draw, (x + width // 2, y + 22), value, 24, "#ffffff", bold=True, anchor="mm")
    return width


def terminal(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], commands: list[str]) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=22, fill="#10242b")
    for index, color in enumerate(("#ff6b6b", "#ffd166", "#06d6a0")):
        draw.ellipse((x1 + 24 + index * 30, y1 + 22, x1 + 42 + index * 30, y1 + 40), fill=color)
    y = y1 + 78
    for command in commands:
        text(draw, (x1 + 30, y), "$", 24, CYAN, bold=True, mono=True)
        wrapped(draw, (x1 + 60, y), command, 24, x2 - x1 - 90, "#f4fbfc", spacing=7)
        y += 65 if len(command) < 54 else 94


def bar(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    label: str,
    value: str,
    ratio: float,
    color: str,
) -> None:
    text(draw, (x, y), label, 28, INK, bold=True)
    text(draw, (x + width, y), value, 30, color, bold=True, anchor="ra")
    draw.rounded_rectangle((x, y + 54, x + width, y + 102), radius=24, fill="#dce8ea")
    draw.rounded_rectangle((x, y + 54, x + int(width * ratio), y + 102), radius=24, fill=color)


def draw_slide(index: int) -> Image.Image:
    image = gradient_background()
    draw = ImageDraw.Draw(image)

    if index == 1:
        banner = Image.open(ROOT / "docs/assets/aetnamem-header.png").convert("RGB")
        banner.thumbnail((1728, 486))
        image.paste(banner, ((WIDTH - banner.width) // 2, 56))
        text(draw, (960, 612), "OPENCLAW × AETNAMEM", 34, TEAL_DARK, bold=True, anchor="mm")
        text(draw, (960, 698), "Remember what matters.", 74, INK, bold=True, anchor="mm")
        text(draw, (960, 788), "Measure what it costs.", 74, BLUE, bold=True, anchor="mm")
        draw.rounded_rectangle((480, 878, 1440, 946), radius=34, fill=TEAL_DARK)
        text(
            draw,
            (960, 912),
            "Same agent · same answers · less memory context",
            31,
            "#ffffff",
            bold=True,
            anchor="mm",
        )
    elif index == 2:
        header(draw, "Setup", "Native OpenClaw vs AetnaMem", "One additional memory layer—still one normal install.")
        rounded_panel(draw, (96, 292, 916, 918))
        rounded_panel(draw, (1004, 292, 1824, 918), outline=TEAL, width=4)
        pill(draw, 136, 330, "NATIVE OPENCLAW", BLUE)
        pill(draw, 1044, 330, "OPENCLAW + AETNAMEM", TEAL_DARK)
        terminal(draw, (136, 408, 876, 610), ["openclaw onboard", "edit MEMORY.md"])
        terminal(
            draw,
            (1044, 408, 1784, 800),
            [
                "pip install aetnamem",
                "openclaw plugins install npm:openclaw-memory-aetnamem@latest --pin",
                "aetnamem setup",
                "openclaw aetnamem setup --single-user --subject you",
            ],
        )
        text(draw, (136, 672), "Durable facts live in an", 29, MUTED)
        text(draw, (136, 716), "always-loaded file.", 39, BLUE, bold=True)
        text(draw, (1044, 818), "10-step wizard · local SQLite", 27, MUTED)
        text(draw, (1044, 858), "No snapshot. No sudo.", 35, TEAL_DARK, bold=True)
        footer(draw, index)
    elif index == 3:
        header(draw, "Mental model", "Four memories. One bounded context pack.")
        cards = [
            ("WORKING", "Context / task state", "working_snapshots", "What am I doing now?", BLUE),
            ("SEMANTIC", "MEMORY.md / facts", "governed records", "What do I know?", TEAL_DARK),
            ("EPISODIC", "History / traces", "outcomes + lessons", "What happened before?", GOLD),
            ("PROCEDURAL", "SKILL.md / runbooks", "versioned skill index", "How should I do it?", RED),
        ]
        for i, (name, agent, aetna, question, color) in enumerate(cards):
            col, row = i % 2, i // 2
            x, y = 96 + col * 864, 292 + row * 316
            rounded_panel(draw, (x, y, x + 816, y + 270), outline=color, width=3)
            pill(draw, x + 32, y + 28, name, color)
            text(draw, (x + 32, y + 92), question, 34, INK, bold=True)
            text(draw, (x + 32, y + 150), f"Agent: {agent}", 26, MUTED)
            text(draw, (x + 32, y + 198), f"AetnaMem: {aetna}", 26, color, bold=True)
        footer(draw, index)
    elif index == 4:
        header(draw, "Context behavior", "Always loaded vs selectively recalled")
        rounded_panel(draw, (96, 292, 916, 918))
        rounded_panel(draw, (1004, 292, 1824, 918), outline=TEAL, width=4)
        pill(draw, 136, 330, "NATIVE MEMORY.md", BLUE)
        pill(draw, 1044, 330, "AETNAMEM memory.db", TEAL_DARK)
        for i in range(8):
            y = 426 + i * 52
            draw.rounded_rectangle((144, y, 858, y + 30), radius=15, fill="#b8cbd1" if i != 5 else BLUE)
        text(draw, (136, 866), "94 facts loaded", 34, BLUE, bold=True)
        for i in range(8):
            y = 426 + i * 52
            fill = TEAL if i in (2, 5) else "#e2ecee"
            width = 714 if i in (2, 5) else 390
            draw.rounded_rectangle((1052, y, 1052 + width, y + 30), radius=15, fill=fill)
        text(draw, (1044, 866), "Only relevant facts enter context", 34, TEAL_DARK, bold=True)
        footer(draw, index)
    elif index == 5:
        header(draw, "Measured protocol", "A real host/model benchmark—not a mock")
        items = [
            ("94", "durable facts"),
            ("19,489", "native memory characters"),
            ("10 × 2", "questions in fresh sessions"),
            ("60", "measured task calls across 3 arms"),
        ]
        for i, (number, label) in enumerate(items):
            x = 96 + i * 432
            rounded_panel(draw, (x, 304, x + 384, 526))
            text(draw, (x + 192, 372), number, 62, TEAL_DARK, bold=True, anchor="mm")
            text(draw, (x + 192, 458), label, 25, MUTED, anchor="mm")
        rounded_panel(draw, (96, 584, 1824, 900), fill="#10242b", outline="#10242b")
        text(draw, (144, 632), "HOST", 24, CYAN, bold=True)
        text(draw, (144, 680), "OpenClaw 2026.7.1-2", 35, "#ffffff", bold=True)
        text(draw, (704, 632), "MODEL", 24, CYAN, bold=True)
        text(draw, (704, 680), "DeepSeek V4 Flash · thinking off", 35, "#ffffff", bold=True)
        text(draw, (144, 770), "MEASURED", 24, CYAN, bold=True)
        text(draw, (144, 818), "tokens · cost · exact answers · retrieval · audit validity", 35, "#ffffff")
        footer(draw, index)
    elif index == 6:
        header(draw, "Result 1", "13.320% fewer prompt tokens", "Same workload. Same questions. Fresh sessions.")
        bar(draw, 150, 348, 1500, "Native MEMORY.md", "596,581", 1.0, BLUE)
        bar(draw, 150, 562, 1500, "Cache-aware AetnaMem", "517,118", 517118 / 596581, TEAL_DARK)
        draw.rounded_rectangle((548, 764, 1372, 898), radius=36, fill="#ffffff", outline=TEAL, width=4)
        text(draw, (960, 808), "−79,463 prompt tokens", 48, TEAL_DARK, bold=True, anchor="mm")
        text(draw, (960, 864), "in this measured workload", 27, MUTED, anchor="mm")
        footer(draw, index)
    elif index == 7:
        header(draw, "Result 2", "Correctness held. Cost moved down.")
        metrics = [
            ("Correct answers", "20/20", "20/20", "equal"),
            ("Target retrieved", "—", "20/20", "verified"),
            ("Provider cost", "$0.056427", "$0.054752", "−2.968%"),
            ("AetnaMem audit", "—", "valid", "verified"),
        ]
        x_positions = (96, 638, 1036, 1434)
        headers = ("METRIC", "NATIVE", "AETNAMEM", "CHANGE")
        for x, value in zip(x_positions, headers):
            text(draw, (x, 320), value, 24, MUTED, bold=True)
        for row, values in enumerate(metrics):
            y = 394 + row * 132
            draw.rounded_rectangle((80, y - 24, 1840, y + 78), radius=22, fill=PANEL if row % 2 == 0 else PANEL_ALT)
            for col, value in enumerate(values):
                fill = TEAL_DARK if col in (2, 3) else INK
                text(draw, (x_positions[col], y), value, 31, fill, bold=col > 0)
        text(draw, (960, 946), "Measured once · reproducible evidence · not a universal promise", 27, MUTED, anchor="mm")
        footer(draw, index)
    elif index == 8:
        header(draw, "Next: Memory Impact", "Did remembering actually change the result?")
        rounded_panel(draw, (96, 304, 1824, 710), outline=TEAL, width=4)
        steps = [
            ("1", "Candidate", "What could be remembered?"),
            ("2", "Assignment", "What was eligible and shown?"),
            ("3", "Outcome", "What did the verifier observe?"),
            ("4", "Impact", "Did memory earn its cost?"),
        ]
        for i, (number, label, detail) in enumerate(steps):
            x = 140 + i * 420
            draw.ellipse((x, 358, x + 76, 434), fill=TEAL_DARK)
            text(draw, (x + 38, 396), number, 31, "#ffffff", bold=True, anchor="mm")
            text(draw, (x, 474), label, 31, INK, bold=True)
            wrapped(draw, (x, 524), detail, 25, 330, MUTED)
            if i < 3:
                draw.line((x + 96, 396, x + 382, 396), fill=CYAN, width=6)
        pill(draw, 630, 770, "EXPERIMENTAL · DEFAULT OFF", RED)
        text(draw, (960, 874), "Instrumentation shipped. Causal benefit not yet claimed.", 31, INK, bold=True, anchor="mm")
        footer(draw, index)
    elif index == 9:
        header(draw, "Get started", "One public package. One agent connection.")
        terminal(
            draw,
            (180, 300, 1740, 748),
            [
                "pip install aetnamem",
                "openclaw plugins install npm:openclaw-memory-aetnamem@latest --pin",
                "aetnamem setup",
                "openclaw aetnamem setup --single-user --subject you",
            ],
        )
        text(draw, (960, 818), "github.com/aetna000/aetnamem", 43, TEAL_DARK, bold=True, anchor="mm")
        text(
            draw,
            (960, 902),
            "AetnaMem remembers whether remembering actually helped.",
            38,
            INK,
            bold=True,
            anchor="mm",
        )
        footer(draw, index)
    else:
        raise ValueError(index)
    return image


NARRATION = [
    "OpenClaw can remember with a native memory file. AetnaMem adds a selective, audited memory layer. The question is not whether both can remember. The question is how much context they spend while staying correct.",
    "On the left is native OpenClaw. On the right, AetnaMem remains one normal pip install, plus the OpenClaw plugin and a ten-step setup wizard. No snapshot package. No sudo. Existing memory tools remain compatible.",
    "Agents use four kinds of memory. Working memory tracks the current task. Semantic memory stores facts. Episodic memory carries useful past outcomes. Procedural memory supplies the right skill. AetnaMem coordinates all four behind one bounded connection.",
    "Native memory can keep a durable file in every prompt. AetnaMem keeps durable facts in memory dot D B and retrieves a small relevant block. The agent still gets the fact it needs, while unrelated facts stay outside the context window.",
    "We tested a synthetic, pre-registered workload: ninety-four facts, nineteen thousand four hundred eighty-nine characters of native memory, ten questions run twice in fresh sessions, and DeepSeek V4 Flash with thinking disabled.",
    "Native memory used five hundred ninety-six thousand five hundred eighty-one prompt tokens. Cache-aware AetnaMem used five hundred seventeen thousand one hundred eighteen. That is seventy-nine thousand four hundred sixty-three fewer prompt tokens, a thirteen point three two percent reduction in this workload.",
    "Both systems answered twenty out of twenty correctly. AetnaMem retrieved the target on twenty out of twenty tasks. Provider-reported cost was two point nine seven percent lower, and the AetnaMem audit chain verified.",
    "The next question is harder. Did a retrieved memory actually cause a better outcome, or did it only consume context? AetnaMem now has a default-off experimental Memory Impact ledger. It records what was eligible, what was shown, and which outcome followed. The instrumentation is shipped. The causal benefit is not yet claimed.",
    "Install the same public package with pip install AetnaMem. Connect OpenClaw, choose a preset, and inspect the evidence. AetnaMem remembers whether remembering actually helped. Read the protocol and source on GitHub dot com slash aetna zero zero zero slash AetnaMem.",
]


def duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def run() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("say"):
        raise SystemExit("ffmpeg and macOS say are required")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aetnamem-video-") as temp:
        temp_dir = Path(temp)
        segments: list[Path] = []
        for index, narration in enumerate(NARRATION, start=1):
            slide = temp_dir / f"slide-{index:02d}.png"
            audio = temp_dir / f"slide-{index:02d}.aiff"
            segment = temp_dir / f"segment-{index:02d}.mp4"
            draw_slide(index).save(slide, quality=95)
            subprocess.run(
                ["say", "-v", "Samantha", "-r", "184", "-o", str(audio), narration],
                check=True,
            )
            seconds = max(5.0, duration(audio) + 0.65)
            fade_out = max(0.1, seconds - 0.45)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-loop",
                    "1",
                    "-framerate",
                    str(FPS),
                    "-i",
                    str(slide),
                    "-i",
                    str(audio),
                    "-t",
                    f"{seconds:.3f}",
                    "-vf",
                    f"format=yuv420p,fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out:.3f}:d=0.45",
                    "-af",
                    f"afade=t=in:st=0:d=0.15,afade=t=out:st={fade_out:.3f}:d=0.35",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-shortest",
                    str(segment),
                ],
                check=True,
            )
            segments.append(segment)
        concat = temp_dir / "segments.txt"
        concat.write_text(
            "".join(f"file '{segment.as_posix()}'\n" for segment in segments),
            encoding="utf-8",
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(OUTPUT),
            ],
            check=True,
        )
    print(OUTPUT)


if __name__ == "__main__":
    run()
