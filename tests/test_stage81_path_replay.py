from __future__ import annotations

import importlib.util
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGE81 = ROOT / "reproduction/81-finite149-portable-verification"
MODULE_PATH = STAGE81 / "scripts/path_replay.py"
SPEC = importlib.util.spec_from_file_location("stage81_path_replay", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
path_replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(path_replay)

CAPTURE_MODULE_PATH = STAGE81 / "scripts/capture_path_sources.py"
CAPTURE_SPEC = importlib.util.spec_from_file_location(
    "stage81_capture_path_sources", CAPTURE_MODULE_PATH
)
assert CAPTURE_SPEC is not None and CAPTURE_SPEC.loader is not None
capture = importlib.util.module_from_spec(CAPTURE_SPEC)
CAPTURE_SPEC.loader.exec_module(capture)


class Stage81PathReplayTests(unittest.TestCase):
    def test_committed_snapshot_replays_all_frozen_path_edges(self) -> None:
        edge_bytes, audit, boundary = path_replay.replay(
            ROOT / "reproduction/80-finite149/raw/finite149-source-snapshot.tar.gz",
            STAGE81 / "raw/finite149-path-source-snapshot.tar.gz",
        )
        self.assertGreater(len(edge_bytes), 0)
        self.assertEqual(
            audit["counts"],
            {
                "dual_edge_instances": 40,
                "dual_paths": 20,
                "edge_instances": 405,
                "failed_edges": 0,
                "path_nodes": 170,
                "paths": 149,
                "reversed_only_edges": 0,
                "source_files": 30,
                "source_mismatches": 0,
                "unique_directed_edges": 159,
            },
        )
        self.assertTrue(boundary["edge_replay_performed"])
        self.assertFalse(boundary["shortest_path_search_performed"])
        self.assertFalse(boundary["upstream_graph_builder_rerun"])

    def test_rejects_tampered_raw_archive_before_parsing(self) -> None:
        original = STAGE81 / "raw/finite149-path-source-snapshot.tar.gz"
        with tempfile.TemporaryDirectory() as temporary:
            tampered = Path(temporary) / original.name
            body = bytearray(original.read_bytes())
            body[-1] ^= 1
            tampered.write_bytes(body)
            with self.assertRaisesRegex(RuntimeError, "raw hash drift"):
                path_replay.validate_stage81_archive(tampered)

    def test_rejects_duplicate_or_non_involutive_dual_endpoints(self) -> None:
        body = b"[[1,2],[2,3]]"
        with self.assertRaisesRegex(RuntimeError, "dual endpoint drift"):
            path_replay.parse_dual_pairs(body)

    def test_equal_weight_graph_edge_keeps_first_insertion(self) -> None:
        entries = {
            "/checkout/equational_theories/First.lean": [
                "i|1|First.proof|2|1"
            ],
            "/checkout/equational_theories/Second.lean": [
                "i|1|Second.proof|2|1"
            ],
        }
        graph, _ = path_replay.build_selected_graph(entries, [], {("1", "2")})
        self.assertEqual(graph[("1", "2")]["filename"], "equational_theories/First.lean")


class Stage81CaptureSafetyTests(unittest.TestCase):
    def test_rejects_unsafe_archive_member(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unsafe archive member"):
            capture.safe_member("../escape")

    def test_rejects_duplicate_archive_members(self) -> None:
        first = tarfile.TarInfo("source/value")
        second = tarfile.TarInfo("source/value")
        with self.assertRaisesRegex(RuntimeError, "duplicate archive member"):
            capture.validate_member_headers([first, second])

    def test_rejects_oversized_archive_member(self) -> None:
        member = tarfile.TarInfo("source/value")
        member.size = capture.MAX_MEMBER_BYTES + 1
        with self.assertRaisesRegex(RuntimeError, "member exceeds cap"):
            capture.validate_member_headers([member])

    def test_rejects_local_symlink_and_parent_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            outside = Path(temporary) / "outside.lean"
            root.mkdir()
            outside.write_text("theorem x : True := by trivial\n", encoding="utf-8")
            (root / "link.lean").symlink_to(outside)
            with self.assertRaisesRegex(RuntimeError, "symlinked local source"):
                capture.resolve_local_source(root, "link.lean")
            with self.assertRaisesRegex(RuntimeError, "unsafe archive member"):
                capture.resolve_local_source(root, "../outside.lean")


if __name__ == "__main__":
    unittest.main()
