#!/usr/bin/env python3
"""Replay every edge of the 149 frozen finite-counterexample proof paths.

This ports the graph-construction rules from the hash-pinned upstream
``show_proof.html``.  It validates the already-recorded paths edge by edge; it
does not rerun upstream extraction or independently search for shortest paths.
Only the small trailing ``full_entries`` object in ``finite_graph.json`` is
decoded, so the large RLE/equivalence payload is never materialized.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import tarfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable


CHUNK_BYTES = 64 * 1024
GRAPH_TAIL_LIMIT_BYTES = 2 * 1024 * 1024
MAX_RAW_MEMBER_BYTES = 10 * 1024 * 1024
MAX_RAW_TOTAL_BYTES = 20 * 1024 * 1024
EXPECTED_STAGE80_RAW_SHA256 = "15dcc1152d014e4a18996d160f0471e85e3c47f7227450c1c2ed2b8bf1dbc237"
EXPECTED_STAGE81_RAW_SHA256 = "127e420e469b1a97d942f851542d99e03d4c30d5f73ec26ada0d04ff97f175df"
EXPECTED_GRAPH_SHA256 = "d609274eeb8289cf28596463626c1e6e3af21c24f76a5bb06167ef6a88a2f679"
EXPECTED_GRAPH_BYTES = 9_042_748
EXPECTED_IMPLICATIONS_SHA256 = "223fe63a555c6c421d02b23d7613fdd652917c11fc71feec5e81e3c1e085edab"
EXPECTED_FULL_ENTRIES_SHA256 = "c33dc30ee4630764b7e9c34addad9a4236b14611aee61834a32c503585cb98d3"
EXPECTED_SHOW_PROOF_SHA256 = "0117a9a3c1d8aa5188b263b2d8aa40394b20e26f380d98718058ce6d392190f2"
EXPECTED_LICENSE_SHA256 = "c6be243aa954228fc83b68a08e769bf3c561a64fb515cbbd470046d006c18bbf"
EXPECTED_PATHS = 149
EXPECTED_EDGE_INSTANCES = 405
EXPECTED_UNIQUE_EDGES = 159
EXPECTED_PATH_NODES = 170
EXPECTED_SOURCE_FILES = 30
EXPECTED_ADDED_SOURCES = 13
EXPECTED_DUAL_PATHS = 20
STAGE80_MANIFEST = "source/finite149/manifest.csv"
STAGE80_BUNDLE = "source/finite149/bundle_manifest.json"
STAGE80_SOURCE_PREFIX = "source/official_sources/"
STAGE81_SOURCE_PREFIX = "source/path_sources/"
GRAPH_MEMBER = "source/upstream/finite_graph.json"
IMPLICATIONS_MEMBER = "source/upstream/implications.js"
FULL_ENTRIES_MEMBER = "source/upstream/full_entries.json"
SHOW_PROOF_MEMBER = "source/upstream/show_proof.html"
LICENSE_MEMBER = "source/license/LICENSE"
DUALS_MEMBER = "data/duals.json"
FULL_ENTRIES_MARKER = b'"full_entries"'
DUALS_RE = re.compile(rb"\bvar\s+duals\s*=\s*")
MISSING_SOURCE_ALLOWLIST = frozenset(
    {
        "equational_theories/Generated/MagmaEgg/small/_000.lean",
        "equational_theories/Generated/MagmaEgg/small/_001.lean",
        "equational_theories/Generated/SimpleRewrites/theorems/Rewrite_wz_yx_zy.lean",
        "equational_theories/Generated/SimpleRewrites/theorems/Rewrite_wz_zx.lean",
        "equational_theories/Generated/SimpleRewrites/theorems/Rewrite_yx.lean",
        "equational_theories/Generated/SimpleRewrites/theorems/Rewrite_yx_zy.lean",
        "equational_theories/Generated/SimpleRewrites/theorems/Rewrite_zx.lean",
        "equational_theories/Generated/SimpleRewrites/theorems/Rewrite_zy.lean",
        "equational_theories/Generated/TrivialBruteforce/theorems/Apply.lean",
        "equational_theories/Generated/TrivialBruteforce/theorems/RewriteCombinations.lean",
        "equational_theories/Generated/TrivialBruteforce/theorems/RewriteHypothesis.lean",
        "equational_theories/Generated/VampireProven/Proofs2.lean",
        "equational_theories/Generated/VampireProven/Proofs4.lean",
    }
)


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def safe_member(name: str) -> None:
    pure = PurePosixPath(name)
    ensure(name and not name.startswith("/"), f"unsafe raw member: {name!r}")
    ensure(".." not in pure.parts and str(pure) == name, f"unsafe raw member: {name!r}")


def hash_stream(stream: BinaryIO) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    while chunk := stream.read(CHUNK_BYTES):
        total += len(chunk)
        digest.update(chunk)
    return total, digest.hexdigest()


def validate_stage81_archive(path: Path) -> tuple[dict[str, object], dict[str, bytes]]:
    ensure(sha256_path(path) == EXPECTED_STAGE81_RAW_SHA256, "Stage 81 path-source raw hash drift")
    small: dict[str, bytes] = {}
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        ensure(len(names) == len(set(names)), "duplicate Stage 81 raw member")
        for member in members:
            safe_member(member.name)
            ensure(member.isfile(), f"non-file Stage 81 raw member: {member.name}")
            ensure(member.size <= MAX_RAW_MEMBER_BYTES, f"oversized Stage 81 raw member: {member.name}")
        ensure(sum(member.size for member in members) <= MAX_RAW_TOTAL_BYTES, "Stage 81 raw total-size cap exceeded")
        ensure("snapshot-metadata.json" in names, "Stage 81 snapshot metadata absent")
        metadata_file = archive.extractfile("snapshot-metadata.json")
        ensure(metadata_file is not None, "cannot read Stage 81 snapshot metadata")
        metadata = json.load(metadata_file)
        declared_rows = metadata["source_files"]
        declared = {row["archive_path"]: row for row in declared_rows}
        ensure(len(declared) == len(declared_rows), "duplicate Stage 81 metadata declaration")
        expected_names = {
            "snapshot-metadata.json",
            GRAPH_MEMBER,
            IMPLICATIONS_MEMBER,
            FULL_ENTRIES_MEMBER,
            SHOW_PROOF_MEMBER,
            LICENSE_MEMBER,
            DUALS_MEMBER,
            *(f"{STAGE81_SOURCE_PREFIX}{name}" for name in MISSING_SOURCE_ALLOWLIST),
        }
        ensure(set(names) == expected_names, "Stage 81 raw allowlist drift")
        ensure(set(declared) == expected_names - {"snapshot-metadata.json"}, "Stage 81 metadata/member set drift")
        ensure(metadata["member_count_excluding_metadata"] == len(declared), "Stage 81 member-count drift")
        ensure(metadata["limits"] == {
            "copy_chunk_bytes": CHUNK_BYTES,
            "max_member_bytes": MAX_RAW_MEMBER_BYTES,
            "max_total_uncompressed_bytes": MAX_RAW_TOTAL_BYTES,
        }, "Stage 81 raw limit declaration drift")
        for name, row in declared.items():
            member = archive.getmember(name)
            ensure(member.size == row["bytes"], f"Stage 81 raw size drift: {name}")
            extracted = archive.extractfile(member)
            ensure(extracted is not None, f"cannot read Stage 81 raw member: {name}")
            if name in {IMPLICATIONS_MEMBER, SHOW_PROOF_MEMBER, DUALS_MEMBER} or name.startswith(STAGE81_SOURCE_PREFIX):
                body = extracted.read()
                total, digest = len(body), sha256_bytes(body)
                small[name] = body
            else:
                total, digest = hash_stream(extracted)
            ensure(total == row["bytes"] and digest == row["sha256"], f"Stage 81 raw identity drift: {name}")
        ensure(declared[GRAPH_MEMBER]["sha256"] == EXPECTED_GRAPH_SHA256, "finite graph metadata hash drift")
        ensure(declared[GRAPH_MEMBER]["bytes"] == EXPECTED_GRAPH_BYTES, "finite graph metadata size drift")
        ensure(declared[IMPLICATIONS_MEMBER]["sha256"] == EXPECTED_IMPLICATIONS_SHA256, "implications.js metadata drift")
        ensure(declared[FULL_ENTRIES_MEMBER]["sha256"] == EXPECTED_FULL_ENTRIES_SHA256, "full_entries metadata drift")
        ensure(declared[SHOW_PROOF_MEMBER]["sha256"] == EXPECTED_SHOW_PROOF_SHA256, "show_proof metadata drift")
        ensure(declared[LICENSE_MEMBER]["sha256"] == EXPECTED_LICENSE_SHA256, "license metadata drift")
    return metadata, small


def load_stage80_inputs(path: Path) -> tuple[list[dict[str, str]], dict[str, object], dict[str, bytes]]:
    ensure(sha256_path(path) == EXPECTED_STAGE80_RAW_SHA256, "Stage 80 raw hash drift")
    wanted = {STAGE80_MANIFEST, STAGE80_BUNDLE}
    bodies: dict[str, bytes] = {}
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        ensure(len(names) == len(set(names)), "duplicate Stage 80 raw member")
        for member in members:
            safe_member(member.name)
            ensure(member.isfile(), f"non-file Stage 80 raw member: {member.name}")
            if member.name in wanted or member.name.startswith(STAGE80_SOURCE_PREFIX):
                extracted = archive.extractfile(member)
                ensure(extracted is not None, f"cannot read Stage 80 member: {member.name}")
                bodies[member.name] = extracted.read()
    ensure(wanted <= set(bodies), "Stage 80 path inputs absent")
    paths = list(csv.DictReader(io.StringIO(bodies[STAGE80_MANIFEST].decode("utf-8-sig"))))
    bundle = json.loads(bodies[STAGE80_BUNDLE])
    sources = {
        name[len(STAGE80_SOURCE_PREFIX) :]: body
        for name, body in bodies.items()
        if name.startswith(STAGE80_SOURCE_PREFIX)
    }
    return paths, bundle, sources


def parse_dual_pairs(body: bytes) -> list[list[int]]:
    value = json.loads(body)
    ensure(isinstance(value, list), "duals.json is not an array")
    pairs: list[list[int]] = []
    seen: set[int] = set()
    for pair in value:
        ensure(isinstance(pair, list) and len(pair) == 2, "malformed dual pair")
        ensure(all(isinstance(item, int) for item in pair), "non-integer dual endpoint")
        left, right = pair
        ensure(left != right and left not in seen and right not in seen, f"dual endpoint drift: {pair}")
        seen.update(pair)
        pairs.append([left, right])
    ensure(pairs == sorted(pairs), "dual pair ordering drift")
    return pairs


def parse_implications_duals(body: bytes) -> list[list[int]]:
    match = DUALS_RE.search(body)
    ensure(match is not None, "implications.js dual assignment absent")
    value, _ = json.JSONDecoder().raw_decode(body[match.end() :].decode("utf-8").lstrip())
    return parse_dual_pairs(json.dumps(value).encode("utf-8"))


def extract_graph_entries(path: Path) -> tuple[dict[str, list[str]], dict[str, int | bool]]:
    with tarfile.open(path, "r:gz") as archive:
        member = archive.getmember(GRAPH_MEMBER)
        ensure(member.size == EXPECTED_GRAPH_BYTES, "finite graph member-size drift")
        stream = archive.extractfile(member)
        ensure(stream is not None, "cannot read finite graph member")
        digest = hashlib.sha256()
        total = 0
        tail = bytearray()
        marker_hits = 0
        overlap = b""
        while chunk := stream.read(CHUNK_BYTES):
            total += len(chunk)
            digest.update(chunk)
            marker_hits += (overlap + chunk).count(FULL_ENTRIES_MARKER)
            overlap = (overlap + chunk)[-(len(FULL_ENTRIES_MARKER) - 1) :]
            tail.extend(chunk)
            if len(tail) > GRAPH_TAIL_LIMIT_BYTES:
                del tail[: len(tail) - GRAPH_TAIL_LIMIT_BYTES]
        ensure(total == EXPECTED_GRAPH_BYTES and digest.hexdigest() == EXPECTED_GRAPH_SHA256, "finite graph identity drift")
        ensure(marker_hits == 1, "finite graph full_entries marker-count drift")
    marker_at = tail.find(FULL_ENTRIES_MARKER)
    ensure(marker_at >= 0, "finite graph full_entries exceeds bounded tail")
    remainder = bytes(tail[marker_at + len(FULL_ENTRIES_MARKER) :])
    colon = remainder.find(b":")
    ensure(colon >= 0, "finite graph full_entries separator absent")
    text = remainder[colon + 1 :].decode("utf-8").lstrip()
    entries, end = json.JSONDecoder(object_pairs_hook=dict).raw_decode(text)
    ensure(isinstance(entries, dict), "finite graph full_entries is not an object")
    ensure(text[end:].strip() == "}", "finite graph trailing syntax drift")
    for filename, values in entries.items():
        ensure(isinstance(filename, str) and isinstance(values, list), "malformed full_entries file")
        ensure(all(isinstance(value, str) for value in values), f"malformed entry list: {filename}")
    return entries, {
        "application_tail_limit_bytes": GRAPH_TAIL_LIMIT_BYTES,
        "full_entries_files": len(entries),
        "full_json_materialized": False,
        "graph_bytes_streamed": total,
        "marker_hits": marker_hits,
        "tail_bytes_retained": len(tail),
    }


def normalize_source_path(filepath: str) -> str:
    return re.sub(r"^.*equational_theories/", "equational_theories/", filepath)


def build_selected_graph(
    full_entries: dict[str, list[str]],
    dual_pairs: list[list[int]],
    tracked: set[tuple[str, str]],
) -> tuple[dict[tuple[str, str], dict[str, object]], dict[str, object]]:
    dual_index: dict[str, str] = {}
    for left, right in dual_pairs:
        dual_index[str(left)] = str(right)
        dual_index[str(right)] = str(left)

    def dual(value: object) -> str:
        text = str(value)
        return dual_index.get(text, text)

    def neg(value: object) -> str:
        return f"{value}_neg"

    selected: dict[tuple[str, str], dict[str, object]] = {}
    all_eqs: dict[str, None] = {}
    unconditionals: list[dict[str, object]] = []
    insertion = 0

    def add_edge(
        source: object,
        target: object,
        base_weight: int,
        provenance: dict[str, object],
        *,
        is_dual: bool,
        edge_kind: str,
    ) -> None:
        nonlocal insertion
        insertion += 1
        pair = (str(source), str(target))
        if pair not in tracked:
            return
        weight = base_weight * (3 if is_dual else 1) * (1000 if provenance["is_conjecture"] else 1)
        current = selected.get(pair)
        if current is not None and int(current["weight"]) <= weight:
            return
        selected[pair] = {
            **provenance,
            "edge_kind": edge_kind,
            "from": pair[0],
            "insertion_index": insertion,
            "is_dual": is_dual,
            "to": pair[1],
            "weight": weight,
        }

    facts_counter = 0
    parsed_entries = 0
    for filepath, entries in full_entries.items():
        filename = normalize_source_path(filepath)
        for entry in entries:
            parsed_entries += 1
            fields = entry.split("|")
            ensure(len(fields) >= 4, f"malformed graph entry: {entry!r}")
            kind = entry[0]
            ensure(kind in {"u", "i", "f"}, f"unknown graph entry kind: {entry!r}")
            provenance = {
                "entry": entry,
                "filename": filename,
                "is_conjecture": len(entry) > 1 and entry[1] == "?",
                "line": int(fields[1]),
                "name": fields[2],
            }
            if kind == "u":
                equation = fields[3]
                all_eqs.setdefault(equation, None)
                unconditionals.append({**provenance, "equation": equation})
            elif kind == "i":
                ensure(len(fields) == 5, f"malformed implication entry: {entry!r}")
                lhs, rhs = fields[3], fields[4]
                all_eqs.setdefault(lhs, None)
                all_eqs.setdefault(rhs, None)
                add_edge(rhs, lhs, 1, provenance, is_dual=False, edge_kind="implication")
                add_edge(neg(rhs), neg(lhs), 1, provenance, is_dual=False, edge_kind="implication-negated")
                add_edge(dual(rhs), dual(lhs), 1, provenance, is_dual=True, edge_kind="implication-dual")
                add_edge(neg(dual(rhs)), neg(dual(lhs)), 1, provenance, is_dual=True, edge_kind="implication-dual-negated")
            else:
                ensure(len(fields) == 5, f"malformed facts entry: {entry!r}")
                satisfied, refuted = json.loads(fields[3]), json.loads(fields[4])
                ensure(isinstance(satisfied, list) and isinstance(refuted, list), "malformed facts arrays")
                node = f"Facts{facts_counter}"
                facts_counter += 1
                node_dual = f"Facts{facts_counter}"
                facts_counter += 1
                for equation in satisfied:
                    all_eqs.setdefault(str(equation), None)
                    add_edge(equation, node, 1, provenance, is_dual=False, edge_kind="facts-satisfied")
                    add_edge(dual(equation), node_dual, 1, provenance, is_dual=True, edge_kind="facts-satisfied-dual")
                for equation in refuted:
                    all_eqs.setdefault(str(equation), None)
                    add_edge(node, neg(equation), 1, provenance, is_dual=False, edge_kind="facts-refuted")
                    add_edge(node_dual, neg(dual(equation)), 1, provenance, is_dual=True, edge_kind="facts-refuted-dual")

    for unconditional in unconditionals:
        equation = unconditional["equation"]
        provenance = {key: value for key, value in unconditional.items() if key != "equation"}
        for other in all_eqs:
            add_edge(equation, other, 2, provenance, is_dual=False, edge_kind="unconditional")
            add_edge(neg(equation), neg(other), 2, provenance, is_dual=False, edge_kind="unconditional-negated")
            add_edge(dual(equation), dual(other), 2, provenance, is_dual=True, edge_kind="unconditional-dual")
            add_edge(neg(dual(equation)), neg(dual(other)), 2, provenance, is_dual=True, edge_kind="unconditional-dual-negated")

    return selected, {
        "all_equations": len(all_eqs),
        "facts_nodes_allocated": facts_counter,
        "graph_entries_parsed": parsed_entries,
        "tracked_edge_winners": len(selected),
        "unconditional_entries": len(unconditionals),
    }


def compact_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def gzip_jsonl(rows: Iterable[dict[str, object]]) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0, compresslevel=9) as handle:
        for row in rows:
            handle.write(compact_json_bytes(row) + b"\n")
    return output.getvalue()


def validate_source_line(body: bytes, line: int, theorem_name: str, filename: str) -> str:
    lines = body.decode("utf-8").splitlines()
    ensure(1 <= line <= len(lines), f"source line out of range: {filename}:{line}")
    text = lines[line - 1]
    leaf = theorem_name.rsplit(".", 1)[-1]
    # Upstream extraction points either at the declaration or at its immediately
    # preceding attribute (commonly ``@[equational_result]``).
    declaration_window = "\n".join(lines[line - 1 : line + 2])
    ensure(
        leaf in declaration_window or theorem_name in declaration_window,
        f"theorem name absent near {filename}:{line}: {theorem_name}",
    )
    return text.strip()


def replay(stage80_raw: Path, stage81_raw: Path) -> tuple[bytes, dict[str, object], dict[str, object]]:
    metadata, small = validate_stage81_archive(stage81_raw)
    paths, bundle, sources = load_stage80_inputs(stage80_raw)
    ensure(len(paths) == EXPECTED_PATHS, "frozen path-count drift")
    official = bundle["official_sources"]
    ensure(len(official) == EXPECTED_SOURCE_FILES, "official source-closure drift")
    for relative in MISSING_SOURCE_ALLOWLIST:
        sources[relative] = small[f"{STAGE81_SOURCE_PREFIX}{relative}"]
    ensure(set(sources) == set(official), "captured path-source closure is not exact")
    for relative, spec in official.items():
        body = sources[relative]
        ensure(len(body) == spec["bytes"] and sha256_bytes(body) == spec["sha256"], f"source identity drift: {relative}")

    dual_pairs = parse_dual_pairs(small[DUALS_MEMBER])
    ensure(dual_pairs == parse_implications_duals(small[IMPLICATIONS_MEMBER]), "duals.json/implications.js drift")
    ensure(sha256_bytes(small[SHOW_PROOF_MEMBER]) == EXPECTED_SHOW_PROOF_SHA256, "graph algorithm source drift")

    parsed_paths: list[tuple[dict[str, str], list[str], list[str]]] = []
    wanted: set[tuple[str, str]] = set()
    nodes: set[str] = set()
    edge_instances = 0
    witness_modes: Counter[str] = Counter()
    for path in paths:
        path_nodes = [part.strip() for part in path["proof_path"].split("->")]
        path_sources = [part for part in path["proof_path_sources"].split(";") if part]
        ensure(len(path_nodes) >= 3, f"short frozen path: {path['problem_id']}")
        ensure(path_sources, f"path-source sequence absent: {path['problem_id']}")
        ensure(path_nodes[0] == path["lhs_id"], f"frozen path start drift: {path['problem_id']}")
        ensure(path_nodes[-1] == f"{path['rhs_id']}_neg", f"frozen path end drift: {path['problem_id']}")
        witness_modes[path["witness_mode"]] += 1
        pairs = list(zip(path_nodes, path_nodes[1:]))
        wanted.update(pairs)
        nodes.update(path_nodes)
        edge_instances += len(pairs)
        parsed_paths.append((path, path_nodes, path_sources))
    ensure(edge_instances == EXPECTED_EDGE_INSTANCES, "frozen edge-instance count drift")
    ensure(len(wanted) == EXPECTED_UNIQUE_EDGES, "frozen unique-edge count drift")
    ensure(len(nodes) == EXPECTED_PATH_NODES, "frozen path-node count drift")
    ensure(
        dict(witness_modes) == {"direct": 74, "finite_graph_path": 75},
        "frozen witness-mode split drift",
    )

    tracked = wanted | {(target, source) for source, target in wanted}
    full_entries, streaming = extract_graph_entries(stage81_raw)
    graph, graph_stats = build_selected_graph(full_entries, dual_pairs, tracked)
    rows: list[dict[str, object]] = []
    failed_edges = 0
    reversed_only_edges = 0
    source_mismatches = 0
    dual_paths = 0
    dual_edge_instances = 0
    for path_index, (path, path_nodes, path_sources) in enumerate(parsed_paths):
        uses_dual = path["uses_dual"] == "True"
        dual_paths += int(uses_dual)
        winner_sources: list[str] = []
        path_winners: list[dict[str, object]] = []
        for step_index, (source, target) in enumerate(zip(path_nodes, path_nodes[1:])):
            winner = graph.get((source, target))
            if winner is None:
                failed_edges += 1
                if (target, source) in graph:
                    reversed_only_edges += 1
                continue
            winner_source = str(winner["filename"])
            winner_sources.append(winner_source)
            path_winners.append(winner)
            ensure(winner_source in sources, f"uncaptured winning source: {winner_source}")
            ensure(not winner["is_conjecture"], f"conjectural edge in frozen path: {path['problem_id']}")
            source_line = validate_source_line(
                sources[winner_source],
                int(winner["line"]),
                str(winner["name"]),
                winner_source,
            )
            dual_edge_instances += int(bool(winner["is_dual"]))
            rows.append(
                {
                    "edge_kind": winner["edge_kind"],
                    "filename": winner["filename"],
                    "from": source,
                    "insertion_index": winner["insertion_index"],
                    "is_conjecture": winner["is_conjecture"],
                    "is_dual": winner["is_dual"],
                    "line": winner["line"],
                    "name": winner["name"],
                    "path_index": path_index,
                    "problem_id": path["problem_id"],
                    "source_line": source_line,
                    "source_sha256": official[winner_source]["sha256"],
                    "step_index": step_index,
                    "to": target,
                    "uses_dual_path": uses_dual,
                    "weight": winner["weight"],
                }
            )
        # The manifest stores the stable first-occurrence closure, not one
        # filename per edge: a later edge may reuse an earlier source.
        stable_unique_sources = [
            source
            for index, source in enumerate(winner_sources)
            if source not in winner_sources[:index]
        ]
        if stable_unique_sources != path_sources:
            source_mismatches += 1
        ensure(
            stable_unique_sources == path_sources,
            f"path source-closure drift at {path['problem_id']}: {stable_unique_sources} != {path_sources}",
        )
        facts_winners = [
            winner
            for winner in path_winners
            if str(winner["edge_kind"]).startswith("facts-")
        ]
        ensure(len(facts_winners) == 2, f"path does not traverse exactly one Facts witness: {path['problem_id']}")
        ensure(
            all(bool(winner["is_dual"]) == uses_dual for winner in facts_winners),
            f"uses_dual/Facts-edge drift: {path['problem_id']}",
        )
    ensure(failed_edges == 0, f"unreplayed frozen path edges: {failed_edges}")
    ensure(reversed_only_edges == 0, f"reversed-only frozen path edges: {reversed_only_edges}")
    ensure(source_mismatches == 0, f"frozen path source mismatches: {source_mismatches}")
    ensure(len(rows) == EXPECTED_EDGE_INSTANCES, "replayed edge-instance count drift")
    ensure(dual_paths == EXPECTED_DUAL_PATHS, "dual path-count drift")

    source_usage = Counter(str(row["filename"]) for row in rows)
    edge_kind_usage = Counter(str(row["edge_kind"]) for row in rows)
    raw_declared = {row["archive_path"]: row for row in metadata["source_files"]}
    audit = {
        "algorithm": {
            "captured_source": SHOW_PROOF_MEMBER,
            "captured_source_sha256": EXPECTED_SHOW_PROOF_SHA256,
            "ported_rules": ["i", "f", "u", "neg", "dual", "weight", "insertion-order-first-wins"],
            "shortest_path_search_performed": False,
            "upstream_graph_builder_rerun": False,
            "validation_claim": "all edges of the frozen paths exist under the pinned graph-construction semantics",
        },
        "counts": {
            "dual_edge_instances": dual_edge_instances,
            "dual_paths": dual_paths,
            "edge_instances": len(rows),
            "failed_edges": failed_edges,
            "path_nodes": len(nodes),
            "paths": len(paths),
            "reversed_only_edges": reversed_only_edges,
            "source_files": len(sources),
            "source_mismatches": source_mismatches,
            "unique_directed_edges": len(wanted),
        },
        "dual_mapping": {
            "implications_js_sha256": EXPECTED_IMPLICATIONS_SHA256,
            "pair_count": len(dual_pairs),
            "standalone_matches_implications_js": True,
        },
        "edge_kind_instances": dict(sorted(edge_kind_usage.items())),
        "graph_construction": graph_stats,
        "graph_input": {
            "embedded_full_entries_used": True,
            "finite_graph_bytes": EXPECTED_GRAPH_BYTES,
            "finite_graph_sha256": EXPECTED_GRAPH_SHA256,
            "separate_full_entries_identity_checked": True,
            "separate_full_entries_sha256": EXPECTED_FULL_ENTRIES_SHA256,
            "separate_full_entries_used_for_replay": False,
        },
        "lean_kernel_compilation_performed": False,
        "license": {
            "identifier": "Apache-2.0",
            "text_member": LICENSE_MEMBER,
            "text_sha256": EXPECTED_LICENSE_SHA256,
            "upstream_notice_file_present": False,
        },
        "raw_archive": {
            "member_count": len(raw_declared) + 1,
            "sha256": EXPECTED_STAGE81_RAW_SHA256,
            "total_declared_uncompressed_bytes": sum(int(row["bytes"]) for row in raw_declared.values()),
        },
        "source_edge_instances": dict(sorted(source_usage.items())),
        "streaming": streaming,
    }
    boundary = {
        "captured_path_source_files": EXPECTED_SOURCE_FILES,
        "edge_instances_replayed": len(rows),
        "edge_replay_performed": True,
        "failed_edges": failed_edges,
        "frozen_paths": len(paths),
        "historical_discovery_rerun": False,
        "lean_kernel_compilation_performed": False,
        "missing_path_source_files": [],
        "reversed_only_edges": reversed_only_edges,
        "shortest_path_search_performed": False,
        "unique_directed_edges_replayed": len(wanted),
        "upstream_graph_builder_rerun": False,
    }
    return gzip_jsonl(rows), audit, boundary


def pretty_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def parse_args() -> argparse.Namespace:
    stage = Path(__file__).resolve().parent.parent
    repository = stage.parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage80-raw",
        type=Path,
        default=repository / "reproduction/80-finite149/raw/finite149-source-snapshot.tar.gz",
    )
    parser.add_argument(
        "--stage81-raw",
        type=Path,
        default=stage / "raw/finite149-path-source-snapshot.tar.gz",
    )
    parser.add_argument("--output-dir", type=Path, default=stage)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    edge_bytes, audit, boundary = replay(args.stage80_raw.resolve(), args.stage81_raw.resolve())
    outputs = {
        "normalized/path-edge-replay.jsonl.gz": edge_bytes,
        "verification/path-edge-replay-audit.json": pretty_json_bytes(audit),
        "verification/path-evidence-boundary.json": pretty_json_bytes(boundary),
    }
    for relative, body in outputs.items():
        path = args.output_dir.resolve() / Path(PurePosixPath(relative))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    print(json.dumps({"edge_instances": audit["counts"]["edge_instances"], "paths": audit["counts"]["paths"], "status": "verified"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
