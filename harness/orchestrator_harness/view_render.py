"""Pure rendering for the terminal viewer.

``render(state, width, height, ...)`` turns one ``view_state`` snapshot into
exactly ``height`` terminal lines of exactly ``width`` visible columns.  It
performs no I/O, so the same function drives the live screen, ``view --once``,
and snapshot tests.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .view_state import (
    DONE,
    FAIL,
    NOW,
    SKIP,
    STEPS,
    TODO,
    WAIT,
)

# Colour depth: 0 = none, 1 = 16 colours, 2 = 256 colours, 3 = truecolor.
NO_COLOR, COLOR_16, COLOR_256, COLOR_TRUE = 0, 1, 2, 3

PALETTE: dict[str, tuple[int, int, int]] = {
    "text": (231, 236, 245),
    "muted": (140, 153, 181),
    "faint": (84, 96, 124),
    "live": (122, 215, 240),
    "memory": (245, 184, 97),
    "plan": (183, 156, 255),
    "review": (231, 236, 245),
    "good": (110, 224, 166),
    "bad": (255, 127, 122),
    "attention": (245, 184, 97),
    "idle": (140, 153, 181),
    "bar": (24, 35, 60),
}
_ANSI16 = {
    "text": 97, "muted": 37, "faint": 90, "live": 96, "memory": 93, "plan": 95,
    "review": 97, "good": 92, "bad": 91, "attention": 93, "idle": 37, "bar": 44,
}
STEP_COLORS = ("memory", "memory", "plan", "plan", "live", "review", "good")

UNICODE_GLYPHS = {
    DONE: "●", NOW: "◉", WAIT: "◌", FAIL: "✕", TODO: "○", SKIP: "·",
    "line_done": "━", "line_todo": "┄", "line_skip": " ",
    "select": "▸", "flag": "⚑", "dot": "●", "rule": "─", "key": "⚿",
}
ASCII_GLYPHS = {
    DONE: "#", NOW: "@", WAIT: "o", FAIL: "x", TODO: ".", SKIP: " ",
    "line_done": "=", "line_todo": "-", "line_skip": " ",
    "select": ">", "flag": "!", "dot": "*", "rule": "-", "key": "k",
}


def text_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if text_width(text) <= width:
        return text
    out, used = [], 0
    for ch in text:
        w = text_width(ch)
        if used + w > width - 1:
            break
        out.append(ch)
        used += w
    return "".join(out) + "…"


def _sgr(color: str | None, depth: int, *, bold: bool = False, dim: bool = False, bg: str | None = None) -> str:
    if depth == NO_COLOR:
        return ""
    codes: list[str] = []
    if bold:
        codes.append("1")
    if dim:
        codes.append("2")
    for name, is_bg in ((color, False), (bg, True)):
        if name is None:
            continue
        r, g, b = PALETTE[name]
        if depth == COLOR_TRUE:
            codes.append(f"{48 if is_bg else 38};2;{r};{g};{b}")
        elif depth == COLOR_256:
            index = 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)
            codes.append(f"{48 if is_bg else 38};5;{index}")
        else:
            base = _ANSI16[name]
            codes.append(str(base + 10 if is_bg and base < 90 else base))
    return f"\x1b[{';'.join(codes)}m" if codes else ""


@dataclass
class Line:
    """One styled terminal line built from (text, style) segments."""

    depth: int
    segments: list[tuple[str, str]] = field(default_factory=list)
    width: int = 0

    def add(self, text: str, color: str | None = None, *, bold: bool = False, dim: bool = False,
            bg: str | None = None) -> "Line":
        if text:
            self.segments.append((text, _sgr(color, self.depth, bold=bold, dim=dim, bg=bg)))
            self.width += text_width(text)
        return self

    def pad_to(self, column: int) -> "Line":
        if column > self.width:
            self.add(" " * (column - self.width))
        return self

    def finish(self, width: int, *, bg: str | None = None) -> str:
        reset = "\x1b[0m" if self.depth != NO_COLOR else ""
        fill = _sgr(None, self.depth, bg=bg) if bg else ""
        out: list[str] = []
        used = 0
        for text, style in self.segments:
            remaining = width - used
            if remaining <= 0:
                break
            if text_width(text) > remaining:
                text = _truncate(text, remaining)
            out.append(f"{fill}{style}{text}{reset}" if (style or fill) else text)
            used += text_width(text)
        if used < width:
            out.append(f"{fill}{' ' * (width - used)}{reset}" if fill else " " * (width - used))
        return "".join(out)


_ASCII_MAP = str.maketrans({"·": "-", "…": ".", "→": ">", "↑": "^", "↓": "v", "─": "-", "━": "="})


def _asciify(line: str) -> str:
    """Replace every non-ASCII character with same-width ASCII."""
    line = line.translate(_ASCII_MAP)
    if line.isascii():
        return line
    return "".join(ch if ch.isascii() else "?" * text_width(ch) for ch in line)


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _age(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds // 3600)}h"


def _track(line: Line, steps: list[str], *, spacing: int, glyphs: dict[str, str], pulse: bool) -> None:
    """Draw the seven connected step nodes."""
    for index, code in enumerate(steps):
        color = STEP_COLORS[index]
        node = glyphs[code]
        if code == DONE:
            line.add(node, color)
        elif code == NOW:
            line.add(node, color, bold=pulse, dim=not pulse)
        elif code == WAIT:
            line.add(node, "attention")
        elif code == FAIL:
            line.add(node, "bad", bold=True)
        else:
            line.add(node, "faint")
        if index == len(steps) - 1 or spacing <= 1:
            continue
        nxt = steps[index + 1]
        if code == DONE and nxt in (DONE, NOW, WAIT, FAIL):
            line.add(glyphs["line_done"] * (spacing - 1), color)
        elif code == SKIP and nxt == SKIP:
            line.add(glyphs["line_skip"] * (spacing - 1))
        else:
            line.add(glyphs["line_todo"] * (spacing - 1), "faint")


def _lane_counts(lanes: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"working": 0, "review": 0, "waiting": 0, "done": 0, "problem": 0}
    for lane in lanes:
        tone = lane["tone"]
        if tone == "live":
            counts["working"] += 1
        elif lane["label"] == "Needs your review":
            counts["review"] += 1
        elif tone == "good":
            counts["done"] += 1
        elif tone == "bad":
            counts["problem"] += 1
        else:
            counts["waiting"] += 1
    return counts


def _header(state: dict[str, Any], width: int, depth: int, glyphs: dict[str, str]) -> list[str]:
    top = Line(depth)
    top.add(" HARNESS ", "text", bold=True, bg="bar")
    epoch = str(state.get("epoch_id") or "")[:8]
    if epoch:
        top.add(f" epoch {epoch}", "muted", bg="bar").add(f" · {state.get('mode') or '?'}", "muted", bg="bar")
    status = state.get("status")
    if status == "closed":
        top.add("  RUN CLOSED", "good", bold=True, bg="bar")
    right = Line(depth)
    monitor = state.get("monitor") or {}
    if status == "open":
        healthy = monitor.get("state") == "healthy"
        right.add(glyphs["dot"] + " ", "good" if healthy else "bad", bg="bar")
        right.add(
            f"monitor {_age(monitor.get('age_seconds'))}" if healthy else "monitor stale",
            "muted", bg="bar",
        )
        right.add("   ", bg="bar")
    right.add(_duration(state.get("run_seconds")) + " ", "text", bold=True, bg="bar")
    top.pad_to(max(top.width, width - right.width))
    top.segments.extend(right.segments)
    top.width += right.width

    lanes = state.get("lanes") or []
    counts = _lane_counts(lanes)
    stats = Line(depth).add(" ")
    parts = [
        (counts["working"], "working", "live"),
        (counts["review"], "to review", "attention"),
        (counts["waiting"], "waiting", "muted"),
        (counts["problem"], "stuck", "bad"),
        (counts["done"], "accepted", "good"),
    ]
    first = True
    for number, noun, color in parts:
        if number == 0 and noun in ("stuck", "to review"):
            continue
        if not first:
            stats.add("   ")
        stats.add(str(number), color, bold=True).add(f" {noun}", "muted")
        first = False
    if state.get("keys_held"):
        stats.add("   ").add(f"{glyphs['key']} {state['keys_held']}", "memory").add(" keys held", "muted")
    return [top.finish(width, bg="bar"), stats.finish(width), Line(depth).add(glyphs["rule"] * width, "faint").finish(width)]


@dataclass
class _Layout:
    compact: bool
    id_w: int
    task_w: int
    spacing: int
    label_w: int
    track_w: int


def _layout(lanes: list[dict[str, Any]], width: int) -> _Layout:
    id_w = max([len(str(lane["lane_id"])) for lane in lanes] + [6])
    label_w = 26
    # Fixed columns: select marker (3), id, gap (2), task, gap (2), track,
    # gap (3), label, elapsed time (7).
    fixed = 3 + id_w + 2 + 2 + 3 + label_w + 7
    for spacing in (9, 8, 7):
        track_w = spacing * (len(STEPS) - 1) + 1
        task_w = width - fixed - track_w
        if task_w >= 16:
            return _Layout(False, id_w, min(task_w, 40), spacing, label_w, track_w)
    track_w = len(STEPS)
    task_w = max(8, width - fixed - track_w)
    return _Layout(True, id_w, task_w, 1, label_w, track_w)


def _lane_lines(lane: dict[str, Any], layout: _Layout, width: int, depth: int, glyphs: dict[str, str],
                *, selected: bool, pulse: bool) -> list[str]:
    tone = lane["tone"]
    first = Line(depth)
    first.add(f" {glyphs['select']} " if selected else "   ", "live", bold=True)
    first.add(str(lane["lane_id"]).ljust(layout.id_w), "text", bold=selected)
    first.add("  ")
    task = lane.get("task") or "(no task text)"
    first.add(_truncate(task, layout.task_w).ljust(layout.task_w), "text" if lane.get("task") else "faint")
    first.add("  ")
    _track(first, lane["steps"], spacing=layout.spacing, glyphs=glyphs, pulse=pulse)
    first.add("   ")
    label_color = {"live": "live", "memory": "memory", "plan": "plan", "attention": "attention",
                   "good": "good", "bad": "bad"}.get(tone, "muted")
    label = lane["label"]
    if layout.compact:
        label = f"{STEPS[lane['current']]}: {label}"
    first.add(_truncate(label, layout.label_w).ljust(layout.label_w), label_color, bold=tone in ("attention", "bad"))
    first.add(_duration(lane.get("elapsed_seconds")).rjust(7), "faint")

    second = Line(depth)
    second.add(" " * (3 + layout.id_w + 2))
    who = " · ".join(str(x) for x in (lane.get("provider"), lane.get("model")) if x)
    second.add(_truncate(who, layout.task_w).ljust(layout.task_w), "faint")
    second.add("  ")
    extras: list[tuple[str, str]] = []
    if lane.get("detail"):
        extras.append((lane["detail"], "memory"))
    elif all(code == SKIP for code in lane["steps"][:4]):
        extras.append(("no memory handoff", "faint"))
    if lane.get("attempts", 0) > 1:
        extras.append((f"try {lane['attempts']} of 6", "live"))
    if lane.get("resumed"):
        extras.append(("resumed run", "plan"))
    for key in lane.get("keys") or []:
        extras.append((f"{glyphs['key']} {key}", "memory"))
    for key in lane.get("orphaned_keys") or []:
        extras.append((f"{glyphs['key']} {key} (stuck)", "bad"))
    for index, (text, color) in enumerate(extras):
        if index:
            second.add("  ·  ", "faint")
        second.add(text, color)
    return [first.finish(width), second.finish(width)]


def _step_header(layout: _Layout, width: int, depth: int) -> str:
    line = Line(depth)
    line.add(" " * (3 + layout.id_w + 2 + layout.task_w + 2))
    if layout.compact:
        line.add("steps", "muted")
    else:
        for index, name in enumerate(STEPS):
            cell = name if index == len(STEPS) - 1 else name.ljust(layout.spacing)
            line.add(cell, STEP_COLORS[index] if index != 5 else "muted", bold=True)
    return line.finish(width)


def _centered(message: str, width: int, depth: int, color: str = "muted") -> str:
    pad = max(0, (width - text_width(message)) // 2)
    return Line(depth).add(" " * pad).add(message, color).finish(width)


def _details(lane: dict[str, Any], width: int, depth: int, glyphs: dict[str, str], pulse: bool) -> list[str]:
    lines = [
        Line(depth).add(f" {lane['lane_id']}", "text", bold=True).add(f"   {lane.get('task') or ''}", "muted").finish(width),
        Line(depth).finish(width),
    ]
    descriptions = {
        0: "Look up past experience and locally shared procedures.",
        1: "Drop memories that are revoked, out of scope, or a poor fit.",
        2: "Reuse a saved plan, adapt one, or plan fresh; ROOT accepts it.",
        3: "Bundle the task, the accepted plan, and a small memory budget.",
        4: "The worker does the task in its own worktree and writes RESULT.json.",
        5: "ROOT reviews the result and accepts or rejects it.",
        6: "The accepted outcome is recorded for future runs.",
    }
    for index, name in enumerate(STEPS):
        code = lane["steps"][index]
        row = Line(depth).add("   ")
        _track(row, [code], spacing=1, glyphs=glyphs, pulse=pulse)
        row.add(f"  {name.ljust(8)}", STEP_COLORS[index] if code != SKIP else "faint", bold=code in (NOW, WAIT, FAIL))
        state_word = {DONE: "done", NOW: "now", WAIT: "waiting", FAIL: "needs attention",
                      TODO: "", SKIP: "skipped (no memory handoff)"}[code]
        row.add(state_word.ljust(28), "muted")
        row.add(descriptions[index], "faint")
        lines.append(row.finish(width))
    lines.append(Line(depth).finish(width))
    facts = [
        ("Status", lane["label"]),
        ("Provider", " · ".join(str(x) for x in (lane.get("provider"), lane.get("model")) if x) or "—"),
        ("Run", str(lane.get("run_id") or "—")),
        ("Report tries", str(lane.get("attempts") or 0)),
        ("Keys held", ", ".join(lane.get("keys") or []) or "none"),
    ]
    memory = lane.get("memory")
    if memory:
        facts.extend([
            ("Strategy", str(memory.get("strategy") or "—")),
            ("Memories delivered", "—" if memory.get("delivered") is None else str(memory["delivered"])),
            ("Memories omitted", "—" if memory.get("omitted") is None else str(memory["omitted"])),
            ("Memory sources", ", ".join(memory.get("sources") or []) or "—"),
            ("Plan", str(memory.get("plan_branch") or "—")),
        ])
    for name, value in facts:
        lines.append(Line(depth).add(f"   {name.ljust(20)}", "muted").add(value, "text").finish(width))
    return lines


def render(
    state: dict[str, Any],
    width: int,
    height: int,
    *,
    selected: int = 0,
    frame: int = 0,
    depth: int = COLOR_TRUE,
    ascii_only: bool = False,
    details: bool = False,
    interactive: bool = True,
) -> list[str]:
    """Return exactly ``height`` lines, each exactly ``width`` columns wide."""
    width = max(40, width)
    height = max(8, height)
    glyphs = ASCII_GLYPHS if ascii_only else UNICODE_GLYPHS
    pulse = frame % 4 < 2
    lines = _header(state, width, depth, glyphs)
    lanes = state.get("lanes") or []
    status = state.get("status")

    body: list[str] = []
    if status == "no_runtime":
        body = [Line(depth).finish(width), _centered("No harness runtime yet. Run `harness setup` first.", width, depth)]
    elif status == "idle" or not lanes:
        body = [Line(depth).finish(width), _centered("No lanes yet. Bootstrap and launch a lane to see it here.", width, depth)]
    elif details:
        body = _details(lanes[max(0, min(selected, len(lanes) - 1))], width, depth, glyphs, pulse)
    else:
        layout = _layout(lanes, width)
        body.append(_step_header(layout, width, depth))
        body.append(Line(depth).finish(width))
        for index, lane in enumerate(lanes):
            body.extend(_lane_lines(lane, layout, width, depth, glyphs,
                                    selected=interactive and index == selected, pulse=pulse))
            body.append(Line(depth).finish(width))

    needs = state.get("needs_you") or []
    bottom: list[str] = []
    if needs:
        bottom.append(Line(depth).add(glyphs["rule"] * width, "faint").finish(width))
        for item in needs[:3]:
            row = Line(depth).add(f" {glyphs['flag']} ", "attention", bold=True)
            lane_id = str(item.get("lane_id") or "runtime")
            text = str(item["text"])
            if text.startswith(lane_id + " "):
                text = text[len(lane_id) + 1:]
            row.add(lane_id.ljust(max(10, len(lane_id) + 2)), "text", bold=True)
            row.add(text, "attention")
            if item.get("age_seconds") is not None:
                row.add(f" · {_age(item['age_seconds'])}", "muted")
            if item.get("hint"):
                row.add(f"   → {item['hint']}", "faint")
            bottom.append(row.finish(width))
        if len(needs) > 3:
            bottom.append(Line(depth).add(f"   +{len(needs) - 3} more", "muted").finish(width))
    if interactive:
        footer = Line(depth).add(" ")
        keys = [("↑↓" if not ascii_only else "up/down", "select"), ("enter", "back" if details else "details"), ("q", "quit")]
        for index, (key, action) in enumerate(keys):
            if index:
                footer.add("   ")
            footer.add(key, "text", bold=True).add(f" {action}", "muted")
        if status == "closed":
            footer.add("   run closed: showing its final state", "good")
        bottom.append(footer.finish(width, bg="bar"))

    room = height - len(lines) - len(bottom)
    if len(body) > room:
        # Keep the selected lane visible: each lane uses three lines after two header lines.
        start = 0
        if not details and lanes and status not in ("no_runtime", "idle"):
            lane_top = 2 + 3 * selected
            if lane_top + 3 > room:
                start = min(len(body) - room, lane_top + 3 - room)
        body = body[start:start + max(0, room)]
    while len(body) < room:
        body.append(Line(depth).finish(width))
    result = (lines + body + bottom)[:height]
    return [_asciify(line) for line in result] if ascii_only else result
