from __future__ import annotations

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock

from tools import verify_all


ROOT = Path(__file__).resolve().parents[1]


class VerifyAllTests(unittest.TestCase):
    def test_rejects_python39_before_starting_a_subprocess(self) -> None:
        runner = Mock()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            status = verify_all.main([], version_info=(3, 9, 6), runner=runner)

        self.assertEqual(status, 2)
        self.assertIn("Python 3.10+ is required", stderr.getvalue())
        runner.assert_not_called()

    def test_runs_all_steps_with_the_current_interpreter_and_repository_cwd(self) -> None:
        runner = Mock(
            side_effect=lambda command, **kwargs: subprocess.CompletedProcess(command, 0)
        )
        with redirect_stdout(io.StringIO()):
            status = verify_all.main(
                ["--repository-root", str(ROOT)],
                version_info=(3, 12, 0),
                runner=runner,
            )

        self.assertEqual(status, 0)
        self.assertEqual(runner.call_count, 4)
        commands = [call.args[0] for call in runner.call_args_list]
        self.assertTrue(all(command[0] == sys.executable for command in commands))
        self.assertTrue(
            all(call.kwargs == {"cwd": ROOT} for call in runner.call_args_list)
        )
        self.assertEqual(
            commands[-1][1:],
            ["-m", "unittest", "discover", "-s", "tests", "-v"],
        )
        self.assertIn("--skip-repository-verifier", commands[1])
        self.assertIn("--skip-repository-verifier", commands[2])

    def test_stops_at_the_first_failed_step_and_returns_its_status(self) -> None:
        runner = Mock(
            side_effect=[
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 7),
            ]
        )
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            status = verify_all.main([], version_info=(3, 11, 0), runner=runner)

        self.assertEqual(status, 7)
        self.assertEqual(runner.call_count, 2)


if __name__ == "__main__":
    unittest.main()
