from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator_harness import operator_launch, processes, setup, shutdown
from orchestrator_harness.config import HarnessConfig, ResourceManifest
from orchestrator_harness.core import iso_utc
from orchestrator_harness.records import atomic_write_json


_STOPPED_THEN_LATE_WRITE = r"""
import json
import os
import sys
import time
from pathlib import Path

record_path = Path(sys.argv[1])
late_path = Path(sys.argv[2])
deadline = time.monotonic() + 10.0
while time.monotonic() < deadline:
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        time.sleep(0.02)
        continue
    if record.get("stop_requested") is True:
        record["health"] = "STOPPED"
        pending = record_path.with_name(record_path.name + ".child.tmp")
        pending.write_text(json.dumps(record), encoding="utf-8")
        os.replace(pending, record_path)
        # Model post-status process teardown.  A caller that treats the
        # status write as process exit can delete the worktree while this
        # exact monitor incarnation still owns a delayed write.
        time.sleep(1.25)
        late_path.parent.mkdir(parents=True, exist_ok=True)
        late_path.write_text("monitor-exited\n", encoding="utf-8")
        raise SystemExit(0)
    time.sleep(0.02)
raise SystemExit(2)
""".strip()


class MonitorRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.config = HarnessConfig(self.root, self.workspace, "enabled")
        self.manifest = ResourceManifest(())
        setup.set_runtime_state(self.config.runtime_root, "OPEN")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def record(self, **overrides: object) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": setup.MONITOR_SCHEMA,
            "config_identity": "cfg-current",
            "pid": 41,
            "creation_time": "old-creation",
            "started_at": iso_utc(),
            "health": "healthy",
            "last_heartbeat_at": iso_utc(),
            "stop_requested": False,
        }
        value.update(overrides)
        atomic_write_json(setup.monitor_record_path(self.config.runtime_root), value)
        return value

    def call(self) -> dict[str, object]:
        with (
            patch.object(setup, "find_harness_root", return_value=self.root),
            patch.object(setup, "load_config", return_value=self.config),
            patch.object(setup, "load_resource_manifest", return_value=self.manifest),
            patch.object(setup, "compute_config_identity", return_value="cfg-current"),
        ):
            return setup.run_monitor_recover()

    def test_public_cli_exposes_monitor_recover(self) -> None:
        args = operator_launch._build_parser().parse_args(["health", "monitor-recover"])
        self.assertEqual((args.command, args.health_command), ("health", "monitor-recover"))
        with patch.object(setup, "run_monitor_recover", return_value={"ok": True}) as recover:
            self.assertEqual(operator_launch._dispatch(args), {"ok": True})
        recover.assert_called_once_with()

    def test_missing_monitor_starts_one_exact_record(self) -> None:
        with (
            patch.object(setup.processes, "spawn_detached", return_value=SimpleNamespace(pid=77)) as spawn,
            patch.object(setup.processes, "process_identity", return_value={"pid": 77, "creation_time": "new-creation"}),
        ):
            result = self.call()
        self.assertEqual(result["code"], "MONITOR_RECOVERED")
        spawn.assert_called_once()
        self.assertEqual(setup.read_monitor_record(self.config.runtime_root)["creation_time"], "new-creation")

    def test_fresh_live_monitor_is_unchanged(self) -> None:
        before = self.record()
        with (
            patch.object(setup.processes, "identity_matches", return_value=True),
            patch.object(setup.processes, "spawn_detached") as spawn,
        ):
            result = self.call()
        self.assertEqual(result["code"], "MONITOR_HEALTHY")
        spawn.assert_not_called()
        self.assertEqual(setup.read_monitor_record(self.config.runtime_root), before)

    def test_dead_unstopped_monitor_restarts(self) -> None:
        self.record()
        with (
            patch.object(setup.processes, "identity_matches", return_value=False),
            patch.object(setup.processes, "spawn_detached", return_value=SimpleNamespace(pid=78)),
            patch.object(setup.processes, "process_identity", return_value={"pid": 78, "creation_time": "replacement"}),
        ):
            result = self.call()
        self.assertEqual(result["code"], "MONITOR_RECOVERED")
        self.assertEqual(setup.read_monitor_record(self.config.runtime_root)["pid"], 78)

    def test_dead_deliberately_stopped_monitor_is_not_restarted(self) -> None:
        self.record(stop_requested=True, health="STOPPED")
        with (
            patch.object(setup.processes, "identity_matches", return_value=False),
            patch.object(setup.processes, "spawn_detached") as spawn,
        ):
            result = self.call()
        self.assertEqual(result["code"], "MONITOR_DELIBERATELY_STOPPED")
        spawn.assert_not_called()

    def test_marked_stopped_but_alive_does_not_double_start(self) -> None:
        self.record(stop_requested=True)
        with (
            patch.object(setup.processes, "identity_matches", return_value=True),
            patch.object(setup.processes, "spawn_detached") as spawn,
        ):
            result = self.call()
        self.assertEqual(result["code"], "MONITOR_STOP_INCOMPLETE")
        self.assertFalse(result["ok"])
        spawn.assert_not_called()

    def test_stale_live_monitor_is_exactly_stopped_before_replacement(self) -> None:
        self.record(last_heartbeat_at="2020-01-01T00:00:00Z")
        matches = iter([True, False])
        with (
            patch.object(setup.processes, "identity_matches", side_effect=lambda *_: next(matches)),
            patch.object(setup.processes, "terminate_process", return_value=True) as terminate,
            patch.object(setup.processes, "spawn_detached", return_value=SimpleNamespace(pid=79)),
            patch.object(setup.processes, "process_identity", return_value={"pid": 79, "creation_time": "after-hung"}),
        ):
            result = self.call()
        self.assertEqual(result["code"], "MONITOR_RECOVERED")
        terminate.assert_called_once_with(41, "old-creation", force=True)

    def test_unproven_hung_cleanup_never_starts_replacement(self) -> None:
        self.record(last_heartbeat_at="not-a-time")
        with (
            patch.object(setup.processes, "identity_matches", return_value=True),
            patch.object(setup.processes, "terminate_process", return_value=False) as terminate,
            patch.object(setup.processes, "spawn_detached") as spawn,
        ):
            result = self.call()
        self.assertEqual(result["code"], "MONITOR_CLEANUP_UNPROVEN")
        terminate.assert_called_once_with(41, "old-creation", force=True)
        spawn.assert_not_called()

    def test_plain_profile_refuses_automatic_recovery(self) -> None:
        self.config = HarnessConfig(self.root, self.workspace, "disabled")
        with patch.object(setup.processes, "spawn_detached") as spawn:
            result = self.call()
        self.assertEqual(result["code"], "MONITOR_RECOVERY_DISABLED")
        spawn.assert_not_called()

    def test_closed_runtime_refuses_recovery(self) -> None:
        setup.set_runtime_state(self.config.runtime_root, "CLOSED")
        with patch.object(setup.processes, "spawn_detached") as spawn:
            result = self.call()
        self.assertEqual(result["code"], "MONITOR_RUNTIME_NOT_OPEN")
        spawn.assert_not_called()

    def test_shutdown_waits_for_exact_monitor_exit_after_stopped_status(self) -> None:
        """STOPPED is a status transition, not proof the writer has exited."""

        late_path = self.workspace / ".agent-workspace" / "late-monitor-write.txt"
        child = processes.spawn_detached(
            [
                sys.executable,
                "-c",
                _STOPPED_THEN_LATE_WRITE,
                str(setup.monitor_record_path(self.config.runtime_root)),
                str(late_path),
            ],
            cwd=str(self.root),
        )
        identity = processes.process_identity(child.pid)
        self.assertIsNotNone(identity)
        assert identity is not None
        self.record(
            pid=identity["pid"],
            creation_time=identity["creation_time"],
        )
        try:
            with patch.object(shutdown, "MONITOR_WAIT_SECONDS", 4.0):
                shutdown._stop_monitor(self.config.runtime_root)
            self.assertIsNotNone(
                child.poll(),
                "shutdown returned while the exact monitor process was still live",
            )
            self.assertTrue(
                late_path.is_file(),
                "shutdown must wait through the monitor's post-status teardown",
            )
        finally:
            if processes.identity_matches(
                identity["pid"], identity["creation_time"]
            ):
                processes.terminate_process(
                    identity["pid"], identity["creation_time"], force=True
                )
            try:
                child.wait(timeout=5.0)
            except (OSError, subprocess.TimeoutExpired):
                pass


if __name__ == "__main__":
    unittest.main()
