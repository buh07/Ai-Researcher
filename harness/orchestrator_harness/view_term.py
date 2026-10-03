"""``operator_launch view``: a read-only, terminal-native lane viewer.

The interactive screen uses only the standard library: ANSI escape sequences
for drawing, ``msvcrt`` for keys on Windows, and ``termios``/``select`` on
POSIX.  It re-reads runtime records every refresh interval, redraws only the
lines that changed, and always restores the terminal on exit.  It never
writes runtime records and is not a harness-managed process.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, TextIO

from . import view_render, view_state

VIEW_OK = "VIEW_OK"
VIEW_CONFIG_INVALID = "VIEW_CONFIG_INVALID"

FRAME_SECONDS = 0.25
DEFAULT_REFRESH_SECONDS = 2.0

_ENTER_SCREEN = "\x1b[?1049h\x1b[?25l\x1b[2J"
_LEAVE_SCREEN = "\x1b[0m\x1b[?25h\x1b[?1049l"
_SYNC_BEGIN = "\x1b[?2026h"
_SYNC_END = "\x1b[?2026l"


def color_depth(stream: TextIO, *, no_color: bool = False) -> int:
    """Pick a colour depth from the environment; NO_COLOR always wins."""
    if no_color or os.environ.get("NO_COLOR") or not _is_tty(stream):
        return view_render.NO_COLOR
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit") or os.environ.get("WT_SESSION"):
        return view_render.COLOR_TRUE
    if "256" in os.environ.get("TERM", "") or os.name == "nt":
        return view_render.COLOR_256
    return view_render.COLOR_16


def _is_tty(stream: Any) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def _enable_windows_vt() -> None:
    """Turn on ANSI processing for the Windows console (no-op elsewhere)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


class _Keys:
    """Non-blocking key reader returning 'up', 'down', 'enter', 'escape', 'q', or None."""

    def __init__(self) -> None:
        self._saved: Any = None

    @contextmanager
    def raw(self) -> Iterator["_Keys"]:
        if os.name == "nt":
            yield self
            return
        import termios
        import tty

        fd = sys.stdin.fileno()
        self._saved = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            yield self
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, self._saved)

    def read(self, timeout: float) -> str | None:
        if os.name == "nt":
            return self._read_windows(timeout)
        return self._read_posix(timeout)

    @staticmethod
    def _read_windows(timeout: float) -> str | None:
        import msvcrt

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    code = msvcrt.getwch()
                    return {"H": "up", "P": "down"}.get(code)
                return _map_char(ch)
            time.sleep(0.02)
        return None

    @staticmethod
    def _read_posix(timeout: float) -> str | None:
        import select

        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return None
        ch = os.read(sys.stdin.fileno(), 1).decode("utf-8", errors="ignore")
        if ch != "\x1b":
            return _map_char(ch)
        ready, _, _ = select.select([sys.stdin], [], [], 0.03)
        if not ready:
            return "escape"
        rest = os.read(sys.stdin.fileno(), 8).decode("utf-8", errors="ignore")
        return {"[A": "up", "[B": "down", "OA": "up", "OB": "down"}.get(rest[:2], None)


def _map_char(ch: str) -> str | None:
    if ch in ("\r", "\n"):
        return "enter"
    if ch == "\x1b":
        return "escape"
    if ch in ("q", "Q", "\x03"):
        return "q"
    if ch in ("k", "K"):
        return "up"
    if ch in ("j", "J"):
        return "down"
    return None


def _terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size((120, 32))
    return size.columns, size.lines


def _safe_collect(collect: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return collect()
    except Exception as exc:  # the viewer reports, never crashes on a bad record
        return {"status": "no_runtime", "lanes": [], "needs_you": [
            {"lane_id": None, "text": f"viewer could not read runtime: {exc}", "hint": "", "age_seconds": None}
        ], "monitor": {}, "run_seconds": None}


def run_interactive(
    collect: Callable[[], dict[str, Any]],
    *,
    out: TextIO = sys.stdout,
    depth: int,
    ascii_only: bool,
    refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
) -> None:
    """Draw the live screen until the user quits."""
    _enable_windows_vt()
    keys = _Keys()
    state = _safe_collect(collect)
    last_collect = time.monotonic()
    selected, details, frame = 0, False, 0
    previous: list[str] = []
    previous_size = (0, 0)
    out.write(_ENTER_SCREEN)
    out.flush()
    try:
        with keys.raw():
            while True:
                now = time.monotonic()
                if now - last_collect >= refresh_seconds:
                    state = _safe_collect(collect)
                    last_collect = now
                lane_count = len(state.get("lanes") or [])
                selected = max(0, min(selected, lane_count - 1)) if lane_count else 0
                width, height = _terminal_size()
                if (width, height) != previous_size:
                    previous = []
                    previous_size = (width, height)
                    out.write("\x1b[2J")
                lines = view_render.render(
                    state, width, height, selected=selected, frame=frame,
                    depth=depth, ascii_only=ascii_only, details=details,
                )
                chunks = [_SYNC_BEGIN]
                for row, line in enumerate(lines):
                    if row >= len(previous) or previous[row] != line:
                        chunks.append(f"\x1b[{row + 1};1H{line}")
                chunks.append(_SYNC_END)
                out.write("".join(chunks))
                out.flush()
                previous = lines
                frame += 1

                key = keys.read(FRAME_SECONDS)
                if key == "q":
                    break
                if key == "up":
                    selected = max(0, selected - 1)
                elif key == "down":
                    selected = min(max(0, lane_count - 1), selected + 1)
                elif key == "enter" and lane_count:
                    details = not details
                elif key == "escape":
                    details = False
    except KeyboardInterrupt:
        pass
    finally:
        out.write(_LEAVE_SCREEN)
        out.flush()


def run_view(
    *,
    once: bool = False,
    no_color: bool = False,
    ascii_only: bool = False,
    refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
    out: TextIO | None = None,
) -> dict[str, Any]:
    """Public ``view`` entry point returning the standard structured result."""
    out = out or sys.stdout
    try:
        from .config import find_harness_root, load_config

        config = load_config(find_harness_root())
    except Exception as exc:
        return {
            "ok": False,
            "code": VIEW_CONFIG_INVALID,
            "summary": str(exc),
            "evidence_paths": [],
            "next_action": "configure the harness, then run `harness setup`",
        }
    rt = config.runtime_root

    def collect() -> dict[str, Any]:
        return view_state.collect_state(rt)

    interactive = not once and _is_tty(out) and _is_tty(sys.stdin)
    depth = color_depth(out, no_color=no_color)
    if not interactive:
        state = _safe_collect(collect)
        width, _ = _terminal_size() if _is_tty(out) else (120, 0)
        lanes = len(state.get("lanes") or [])
        needs = min(3, len(state.get("needs_you") or []))
        height = 3 + 2 + 3 * max(1, lanes) + (needs + 1 if needs else 0)
        lines = view_render.render(
            state, width, height, depth=depth, ascii_only=ascii_only, interactive=False,
        )
        return {
            "ok": True,
            "code": VIEW_OK,
            "summary": "\n".join(line.rstrip() for line in lines),
            "evidence_paths": [str(rt)],
            "next_action": "run `view` in a terminal for the live screen",
            "state": state,
        }
    from . import view_launch

    record = view_launch.record_viewer(rt)
    try:
        run_interactive(collect, out=out, depth=depth, ascii_only=ascii_only, refresh_seconds=refresh_seconds)
    finally:
        view_launch.clear_viewer(record)
    return {
        "ok": True,
        "code": VIEW_OK,
        "summary": "viewer closed",
        "evidence_paths": [],
        "next_action": "none",
    }
