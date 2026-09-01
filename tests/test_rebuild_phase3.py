from __future__ import annotations

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import Mock

from tools import rebuild_phase3


ROOT = Path(__file__).resolve().parents[1]


class RebuildPhase3Tests(unittest.TestCase):
    def test_rejects_python39_before_starting_the_stage_builder(self) -> None:
        runner = Mock()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            status = rebuild_phase3.main(
                ["--repository-root", str(ROOT)],
                version_info=(3, 9, 6),
                runner=runner,
            )

        self.assertEqual(status, 2)
        self.assertIn("Phase 3 requires Python 3.10+", stderr.getvalue())
        runner.assert_not_called()

    def test_delegates_to_stage81_with_the_current_interpreter(self) -> None:
        runner = Mock(
            side_effect=lambda command, **kwargs: subprocess.CompletedProcess(
                command, 0
            )
        )
        status = rebuild_phase3.main(
            ["--repository-root", str(ROOT)],
            version_info=(3, 12, 0),
            runner=runner,
        )

        self.assertEqual(status, 0)
        runner.assert_called_once()
        command = runner.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(
            command[1],
            str(
                ROOT
                / "reproduction"
                / "81-finite149-portable-verification"
                / "scripts"
                / "rebuild.py"
            ),
        )
        self.assertEqual(runner.call_args.kwargs, {"cwd": ROOT})
        self.assertEqual(
            command[2:],
            [
                "--repository-root",
                str(ROOT),
                "--output-stage",
                str(ROOT / "reproduction/81-finite149-portable-verification"),
                "--stage80",
                str(ROOT / "reproduction/80-finite149"),
                "--script-source-stage",
                str(ROOT / "reproduction/81-finite149-portable-verification"),
            ],
        )

    def test_returns_the_stage_builder_status(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess([], 7))
        status = rebuild_phase3.main(
            ["--repository-root", str(ROOT)],
            version_info=(3, 11, 0),
            runner=runner,
        )

        self.assertEqual(status, 7)


if __name__ == "__main__":
    unittest.main()
