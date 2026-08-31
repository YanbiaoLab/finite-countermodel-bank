#!/usr/bin/env python3
"""Validate Stage 70 coverage scores and derive the 1,470-table core.

The historical coverage run contains only 3,535 CSV rows, so this module keeps
small row/identity indexes in memory.  It never reads the 284M pair bitset or
materializes directed pairs.  CSV input is consumed a bounded physical line at
a time, and candidate tables are joined by their historical compact-JSON digest
rather than by list position.

The public entry point is :func:`derive_positive_marginal_core`.  It is layout
independent: callers provide the two CSV paths/streams and an iterable of Stage
50 table-record mappings.
"""

from __future__ import annotations

import csv
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Iterable, Iterator, Mapping, Sequence, TextIO, Union


MODEL_COUNT = 3_535
EQUATION_COUNT = 62_576
REMAINING_PAIR_UNIVERSE = 284_151_591
INDIVIDUAL_POSITIVE_COUNT = 2_303
INDIVIDUAL_ZERO_COUNT = 1_232
INDIVIDUAL_COVERAGE_SUM = 48_939_148
INDIVIDUAL_COVERAGE_MAX = 6_113_454
POSITIVE_MARGINAL_COUNT = 1_470
ZERO_MARGINAL_COUNT = 2_065
FINAL_UNION_COUNT = 32_336_615
FINAL_REMAINING_COUNT = 251_814_976

INDIVIDUAL_CSV_SHA256 = (
    "e8a5f1ceeebac362a718a9f614c52e4b5595924af2f74a64285ebe83abaec683"
)
DEDUPLICATED_CSV_SHA256 = (
    "0d8277a4261cd089f4e6a986e2270db8dd2f1b501678050ab2419098c716818c"
)

HISTORICAL_ID_SCHEME = "sha256-compact-json-table-v1"
POSITIVE_REASON_CODE = "positive_marginal_284m_residual"
ZERO_REASON_CODE = "zero_marginal_284m_residual"
MAX_CSV_LINE_CHARS = 4_096

INDIVIDUAL_HEADER = (
    "coverage_rank",
    "model_index",
    "order",
    "model_sha256",
    "satisfied_count",
    "refuted_count",
    "raw_pair_count",
    "remaining_pair_coverage_count",
    "outside_284m_pair_count",
    "fraction_of_284m_remaining_pairs",
    "fraction_of_model_raw_pairs_in_284m",
)

DEDUPLICATED_HEADER = (
    "coverage_rank",
    "model_index",
    "order",
    "model_sha256",
    "satisfied_count",
    "refuted_count",
    "raw_pair_count",
    "remaining_pair_coverage_count",
    "new_unique_remaining_pair_count",
    "overlap_remaining_pair_count",
    "cumulative_unique_remaining_pair_count",
    "individual_fraction_of_284m_remaining_pairs",
    "incremental_fraction_of_284m_remaining_pairs",
    "cumulative_fraction_of_284m_remaining_pairs",
)

NORMALIZED_COVERAGE_HEADER = DEDUPLICATED_HEADER + ("canonical_table_id",)

_HEX64_RE = re.compile(r"^[a-f0-9]{64}$")
_TABLE_ID_RE = re.compile(r"^sha256:([a-f0-9]{64})$")
_NONNEGATIVE_INTEGER_RE = re.compile(r"^(?:0|[1-9][0-9]*)$")
_FRACTION_RE = re.compile(r"^(?:0|1)\.[0-9]{12}$")
_FRACTION_QUANTUM = Decimal("0.000000000001")


class Stage70Error(RuntimeError):
    """Base error for Stage 70 parsing, mapping, and selection."""


class Stage70ValidationError(Stage70Error):
    """Raised when historical Stage 70 evidence violates a fixed invariant."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage70ValidationError(message)


@dataclass(frozen=True)
class IndividualCoverageRow:
    coverage_rank: int
    model_index: int
    order: int
    model_sha256: str
    satisfied_count: int
    refuted_count: int
    raw_pair_count: int
    remaining_pair_coverage_count: int
    outside_284m_pair_count: int
    fraction_of_284m_remaining_pairs: str
    fraction_of_model_raw_pairs_in_284m: str

    def common_identity_and_counts(self) -> tuple[object, ...]:
        return (
            self.coverage_rank,
            self.model_index,
            self.order,
            self.model_sha256,
            self.satisfied_count,
            self.refuted_count,
            self.raw_pair_count,
            self.remaining_pair_coverage_count,
        )

    def as_csv_row(self) -> dict[str, str]:
        return {
            "coverage_rank": str(self.coverage_rank),
            "model_index": str(self.model_index),
            "order": str(self.order),
            "model_sha256": self.model_sha256,
            "satisfied_count": str(self.satisfied_count),
            "refuted_count": str(self.refuted_count),
            "raw_pair_count": str(self.raw_pair_count),
            "remaining_pair_coverage_count": str(
                self.remaining_pair_coverage_count
            ),
            "outside_284m_pair_count": str(self.outside_284m_pair_count),
            "fraction_of_284m_remaining_pairs": (
                self.fraction_of_284m_remaining_pairs
            ),
            "fraction_of_model_raw_pairs_in_284m": (
                self.fraction_of_model_raw_pairs_in_284m
            ),
        }


@dataclass(frozen=True)
class DeduplicatedCoverageRow:
    coverage_rank: int
    model_index: int
    order: int
    model_sha256: str
    satisfied_count: int
    refuted_count: int
    raw_pair_count: int
    remaining_pair_coverage_count: int
    new_unique_remaining_pair_count: int
    overlap_remaining_pair_count: int
    cumulative_unique_remaining_pair_count: int
    individual_fraction_of_284m_remaining_pairs: str
    incremental_fraction_of_284m_remaining_pairs: str
    cumulative_fraction_of_284m_remaining_pairs: str

    def common_identity_and_counts(self) -> tuple[object, ...]:
        return (
            self.coverage_rank,
            self.model_index,
            self.order,
            self.model_sha256,
            self.satisfied_count,
            self.refuted_count,
            self.raw_pair_count,
            self.remaining_pair_coverage_count,
        )

    def as_csv_row(self) -> dict[str, str]:
        return {
            "coverage_rank": str(self.coverage_rank),
            "model_index": str(self.model_index),
            "order": str(self.order),
            "model_sha256": self.model_sha256,
            "satisfied_count": str(self.satisfied_count),
            "refuted_count": str(self.refuted_count),
            "raw_pair_count": str(self.raw_pair_count),
            "remaining_pair_coverage_count": str(
                self.remaining_pair_coverage_count
            ),
            "new_unique_remaining_pair_count": str(
                self.new_unique_remaining_pair_count
            ),
            "overlap_remaining_pair_count": str(
                self.overlap_remaining_pair_count
            ),
            "cumulative_unique_remaining_pair_count": str(
                self.cumulative_unique_remaining_pair_count
            ),
            "individual_fraction_of_284m_remaining_pairs": (
                self.individual_fraction_of_284m_remaining_pairs
            ),
            "incremental_fraction_of_284m_remaining_pairs": (
                self.incremental_fraction_of_284m_remaining_pairs
            ),
            "cumulative_fraction_of_284m_remaining_pairs": (
                self.cumulative_fraction_of_284m_remaining_pairs
            ),
        }


@dataclass(frozen=True)
class CandidateTableRecord:
    candidate_position: int
    canonical_table_id: str
    historical_model_sha256: str
    order: int
    record: Mapping[str, object]


@dataclass(frozen=True)
class MappedCoverageScore:
    individual: IndividualCoverageRow
    deduplicated: DeduplicatedCoverageRow
    candidate: CandidateTableRecord

    def as_normalized_csv_row(self) -> dict[str, str]:
        row = self.deduplicated.as_csv_row()
        row["canonical_table_id"] = self.candidate.canonical_table_id
        return row


@dataclass(frozen=True)
class SelectionDecision:
    action: str
    reason_code: str
    coverage_rank: int
    model_index: int
    candidate_position: int
    canonical_table_id: str
    historical_model_sha256: str
    order: int
    remaining_pair_coverage_count: int
    new_unique_remaining_pair_count: int
    overlap_remaining_pair_count: int
    cumulative_unique_remaining_pair_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "reason_code": self.reason_code,
            "coverage_rank": self.coverage_rank,
            "model_index": self.model_index,
            "candidate_position": self.candidate_position,
            "canonical_table_id": self.canonical_table_id,
            "historical_model_sha256": self.historical_model_sha256,
            "order": self.order,
            "remaining_pair_coverage_count": (
                self.remaining_pair_coverage_count
            ),
            "new_unique_remaining_pair_count": (
                self.new_unique_remaining_pair_count
            ),
            "overlap_remaining_pair_count": self.overlap_remaining_pair_count,
            "cumulative_unique_remaining_pair_count": (
                self.cumulative_unique_remaining_pair_count
            ),
        }


@dataclass(frozen=True)
class Stage70Summary:
    candidate_count: int
    positive_marginal_count: int
    zero_marginal_count: int
    final_union_count: int
    remaining_uncovered_count: int

    def as_dict(self) -> dict[str, int]:
        return {
            "candidate_count": self.candidate_count,
            "positive_marginal_count": self.positive_marginal_count,
            "zero_marginal_count": self.zero_marginal_count,
            "final_union_count": self.final_union_count,
            "remaining_uncovered_count": self.remaining_uncovered_count,
        }


@dataclass(frozen=True)
class Stage70Result:
    """Validated Stage 70 join and its two deterministic membership outputs."""

    scores: tuple[MappedCoverageScore, ...]
    core_records: tuple[Mapping[str, object], ...]
    positive_decisions: tuple[SelectionDecision, ...]
    removal_metadata: tuple[SelectionDecision, ...]
    summary: Stage70Summary

    def normalized_coverage_rows(self) -> Iterator[dict[str, str]]:
        for score in self.scores:
            yield score.as_normalized_csv_row()


CsvSource = Union[str, os.PathLike[str], TextIO]


@contextmanager
def _open_text_source(source: CsvSource) -> Iterator[TextIO]:
    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        if path.name.endswith(".gz"):
            with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                yield handle
        else:
            with path.open("r", encoding="utf-8", newline="") as handle:
                yield handle
        return
    if not hasattr(source, "readline"):
        raise TypeError("CSV source must be a path or text stream")
    yield source


def _bounded_lines(
    handle: TextIO, context: str, *, limit: int = MAX_CSV_LINE_CHARS
) -> Iterator[str]:
    while True:
        line = handle.readline(limit + 1)
        if line == "":
            return
        if not isinstance(line, str):
            raise TypeError(f"{context}: expected a text stream")
        _require(len(line) <= limit, f"{context}: CSV line exceeds {limit} characters")
        _require("\x00" not in line, f"{context}: NUL byte in CSV input")
        _require("\r" not in line, f"{context}: historical CSV must use LF line endings")
        _require(line != "\n", f"{context}: blank CSV line")
        yield line


def _load_csv_dicts(
    source: CsvSource,
    expected_header: tuple[str, ...],
    expected_sha256: str | None,
    context: str,
) -> tuple[dict[str, str], ...]:
    digest = hashlib.sha256()
    digest.update((",".join(expected_header) + "\n").encode("utf-8"))
    rows: list[dict[str, str]] = []
    with _open_text_source(source) as handle:
        reader = csv.DictReader(_bounded_lines(handle, context))
        _require(tuple(reader.fieldnames or ()) == expected_header, f"{context}: header drift")
        for row_number, row in enumerate(reader, start=1):
            _require(None not in row, f"{context}: extra CSV cell at row {row_number}")
            _require(
                set(row) == set(expected_header),
                f"{context}: field set drift at row {row_number}",
            )
            values = []
            normalized: dict[str, str] = {}
            for field in expected_header:
                value = row[field]
                _require(
                    value is not None and value != "",
                    f"{context}: empty {field} at row {row_number}",
                )
                normalized[field] = value
                values.append(value)
            digest.update((",".join(values) + "\n").encode("utf-8"))
            rows.append(normalized)
    if expected_sha256 is not None:
        _require(
            digest.hexdigest() == expected_sha256,
            f"{context}: canonical CSV fingerprint drift: {digest.hexdigest()}",
        )
    return tuple(rows)


def _nonnegative_integer(value: str, context: str) -> int:
    _require(
        bool(_NONNEGATIVE_INTEGER_RE.fullmatch(value)),
        f"{context}: noncanonical integer {value!r}",
    )
    return int(value)


def _fraction(value: str, numerator: int, denominator: int, context: str) -> str:
    _require(
        bool(_FRACTION_RE.fullmatch(value)),
        f"{context}: invalid fixed-point fraction {value!r}",
    )
    _require(denominator >= 0, f"{context}: negative denominator")
    if denominator == 0:
        _require(numerator == 0, f"{context}: nonzero numerator with zero denominator")
        expected = "0.000000000000"
    else:
        with localcontext() as decimal_context:
            decimal_context.prec = 60
            rounded = (Decimal(numerator) / Decimal(denominator)).quantize(
                _FRACTION_QUANTUM,
                rounding=ROUND_HALF_EVEN,
            )
        expected = format(rounded, ".12f")
    _require(value == expected, f"{context}: fraction drift: {value} != {expected}")
    return value


def _validate_common_counts(
    *,
    context: str,
    coverage_rank: int,
    model_index: int,
    order: int,
    model_sha256: str,
    satisfied_count: int,
    refuted_count: int,
    raw_pair_count: int,
    remaining_pair_coverage_count: int,
) -> None:
    _require(
        1 <= coverage_rank <= MODEL_COUNT,
        f"{context}: coverage rank outside 1..{MODEL_COUNT}",
    )
    _require(0 <= model_index < MODEL_COUNT, f"{context}: model index outside 0..{MODEL_COUNT - 1}")
    _require(5 <= order <= 255, f"{context}: candidate order must be in 5..255")
    _require(bool(_HEX64_RE.fullmatch(model_sha256)), f"{context}: invalid model_sha256")
    _require(
        satisfied_count + refuted_count == EQUATION_COUNT,
        f"{context}: satisfied/refuted counts do not partition {EQUATION_COUNT}",
    )
    _require(
        raw_pair_count == satisfied_count * refuted_count,
        f"{context}: raw_pair_count identity drift",
    )
    _require(
        0 <= remaining_pair_coverage_count <= min(raw_pair_count, REMAINING_PAIR_UNIVERSE),
        f"{context}: remaining coverage outside valid bounds",
    )


def load_individual_coverage(
    source: CsvSource,
    *,
    expected_sha256: str | None = INDIVIDUAL_CSV_SHA256,
) -> tuple[IndividualCoverageRow, ...]:
    """Parse and validate the historical individual-coverage ranking."""

    raw_rows = _load_csv_dicts(
        source,
        INDIVIDUAL_HEADER,
        expected_sha256,
        "Stage70 individual coverage",
    )
    rows: list[IndividualCoverageRow] = []
    seen_indexes = bytearray(MODEL_COUNT)
    seen_hashes: set[str] = set()
    previous_sort_key: tuple[int, int] | None = None
    coverage_sum = 0
    positive_count = 0

    for row_number, raw in enumerate(raw_rows, start=1):
        context = f"Stage70 individual coverage row {row_number}"
        coverage_rank = _nonnegative_integer(raw["coverage_rank"], context)
        model_index = _nonnegative_integer(raw["model_index"], context)
        order = _nonnegative_integer(raw["order"], context)
        satisfied_count = _nonnegative_integer(raw["satisfied_count"], context)
        refuted_count = _nonnegative_integer(raw["refuted_count"], context)
        raw_pair_count = _nonnegative_integer(raw["raw_pair_count"], context)
        remaining_count = _nonnegative_integer(
            raw["remaining_pair_coverage_count"], context
        )
        outside_count = _nonnegative_integer(raw["outside_284m_pair_count"], context)
        model_sha256 = raw["model_sha256"]
        _validate_common_counts(
            context=context,
            coverage_rank=coverage_rank,
            model_index=model_index,
            order=order,
            model_sha256=model_sha256,
            satisfied_count=satisfied_count,
            refuted_count=refuted_count,
            raw_pair_count=raw_pair_count,
            remaining_pair_coverage_count=remaining_count,
        )
        _require(coverage_rank == row_number, f"{context}: noncontiguous ranking")
        _require(not seen_indexes[model_index], f"{context}: duplicate model_index")
        seen_indexes[model_index] = 1
        _require(model_sha256 not in seen_hashes, f"{context}: duplicate model_sha256")
        seen_hashes.add(model_sha256)
        sort_key = (-remaining_count, model_index)
        if previous_sort_key is not None:
            _require(previous_sort_key < sort_key, f"{context}: ranking order drift")
        previous_sort_key = sort_key
        _require(
            outside_count == raw_pair_count - remaining_count,
            f"{context}: outside_284m_pair_count identity drift",
        )
        fraction_remaining = _fraction(
            raw["fraction_of_284m_remaining_pairs"],
            remaining_count,
            REMAINING_PAIR_UNIVERSE,
            context,
        )
        fraction_raw = _fraction(
            raw["fraction_of_model_raw_pairs_in_284m"],
            remaining_count,
            raw_pair_count,
            context,
        )
        coverage_sum += remaining_count
        positive_count += remaining_count > 0
        rows.append(
            IndividualCoverageRow(
                coverage_rank=coverage_rank,
                model_index=model_index,
                order=order,
                model_sha256=model_sha256,
                satisfied_count=satisfied_count,
                refuted_count=refuted_count,
                raw_pair_count=raw_pair_count,
                remaining_pair_coverage_count=remaining_count,
                outside_284m_pair_count=outside_count,
                fraction_of_284m_remaining_pairs=fraction_remaining,
                fraction_of_model_raw_pairs_in_284m=fraction_raw,
            )
        )

    _require(len(rows) == MODEL_COUNT, f"Stage70 individual coverage has {len(rows)} rows")
    _require(all(seen_indexes), "Stage70 individual model_index is not a complete permutation")
    _require(positive_count == INDIVIDUAL_POSITIVE_COUNT, "Stage70 individual positive-count drift")
    _require(
        MODEL_COUNT - positive_count == INDIVIDUAL_ZERO_COUNT,
        "Stage70 individual zero-count drift",
    )
    _require(coverage_sum == INDIVIDUAL_COVERAGE_SUM, "Stage70 individual coverage-sum drift")
    _require(
        max(row.remaining_pair_coverage_count for row in rows)
        == INDIVIDUAL_COVERAGE_MAX,
        "Stage70 individual coverage maximum drift",
    )
    return tuple(rows)


def load_deduplicated_coverage(
    source: CsvSource,
    *,
    expected_sha256: str | None = DEDUPLICATED_CSV_SHA256,
) -> tuple[DeduplicatedCoverageRow, ...]:
    """Parse and validate marginal/cumulative coverage in historical rank order."""

    raw_rows = _load_csv_dicts(
        source,
        DEDUPLICATED_HEADER,
        expected_sha256,
        "Stage70 deduplicated coverage",
    )
    rows: list[DeduplicatedCoverageRow] = []
    seen_indexes = bytearray(MODEL_COUNT)
    seen_hashes: set[str] = set()
    previous_sort_key: tuple[int, int] | None = None
    cumulative = 0
    positive_count = 0

    for row_number, raw in enumerate(raw_rows, start=1):
        context = f"Stage70 deduplicated coverage row {row_number}"
        coverage_rank = _nonnegative_integer(raw["coverage_rank"], context)
        model_index = _nonnegative_integer(raw["model_index"], context)
        order = _nonnegative_integer(raw["order"], context)
        satisfied_count = _nonnegative_integer(raw["satisfied_count"], context)
        refuted_count = _nonnegative_integer(raw["refuted_count"], context)
        raw_pair_count = _nonnegative_integer(raw["raw_pair_count"], context)
        remaining_count = _nonnegative_integer(
            raw["remaining_pair_coverage_count"], context
        )
        new_count = _nonnegative_integer(
            raw["new_unique_remaining_pair_count"], context
        )
        overlap_count = _nonnegative_integer(
            raw["overlap_remaining_pair_count"], context
        )
        declared_cumulative = _nonnegative_integer(
            raw["cumulative_unique_remaining_pair_count"], context
        )
        model_sha256 = raw["model_sha256"]
        _validate_common_counts(
            context=context,
            coverage_rank=coverage_rank,
            model_index=model_index,
            order=order,
            model_sha256=model_sha256,
            satisfied_count=satisfied_count,
            refuted_count=refuted_count,
            raw_pair_count=raw_pair_count,
            remaining_pair_coverage_count=remaining_count,
        )
        _require(coverage_rank == row_number, f"{context}: noncontiguous ranking")
        _require(not seen_indexes[model_index], f"{context}: duplicate model_index")
        seen_indexes[model_index] = 1
        _require(model_sha256 not in seen_hashes, f"{context}: duplicate model_sha256")
        seen_hashes.add(model_sha256)
        sort_key = (-remaining_count, model_index)
        if previous_sort_key is not None:
            _require(previous_sort_key < sort_key, f"{context}: ranking order drift")
        previous_sort_key = sort_key
        _require(
            remaining_count == new_count + overlap_count,
            f"{context}: individual != marginal + overlap",
        )
        cumulative += new_count
        _require(
            declared_cumulative == cumulative,
            f"{context}: cumulative recurrence drift",
        )
        _require(cumulative <= REMAINING_PAIR_UNIVERSE, f"{context}: cumulative exceeds universe")
        individual_fraction = _fraction(
            raw["individual_fraction_of_284m_remaining_pairs"],
            remaining_count,
            REMAINING_PAIR_UNIVERSE,
            context,
        )
        incremental_fraction = _fraction(
            raw["incremental_fraction_of_284m_remaining_pairs"],
            new_count,
            REMAINING_PAIR_UNIVERSE,
            context,
        )
        cumulative_fraction = _fraction(
            raw["cumulative_fraction_of_284m_remaining_pairs"],
            cumulative,
            REMAINING_PAIR_UNIVERSE,
            context,
        )
        positive_count += new_count > 0
        rows.append(
            DeduplicatedCoverageRow(
                coverage_rank=coverage_rank,
                model_index=model_index,
                order=order,
                model_sha256=model_sha256,
                satisfied_count=satisfied_count,
                refuted_count=refuted_count,
                raw_pair_count=raw_pair_count,
                remaining_pair_coverage_count=remaining_count,
                new_unique_remaining_pair_count=new_count,
                overlap_remaining_pair_count=overlap_count,
                cumulative_unique_remaining_pair_count=cumulative,
                individual_fraction_of_284m_remaining_pairs=individual_fraction,
                incremental_fraction_of_284m_remaining_pairs=incremental_fraction,
                cumulative_fraction_of_284m_remaining_pairs=cumulative_fraction,
            )
        )

    _require(len(rows) == MODEL_COUNT, f"Stage70 deduplicated coverage has {len(rows)} rows")
    _require(all(seen_indexes), "Stage70 deduplicated model_index is not a complete permutation")
    _require(positive_count == POSITIVE_MARGINAL_COUNT, "Stage70 positive-marginal count drift")
    _require(
        MODEL_COUNT - positive_count == ZERO_MARGINAL_COUNT,
        "Stage70 zero-marginal count drift",
    )
    _require(cumulative == FINAL_UNION_COUNT, "Stage70 final deduplicated union drift")
    _require(
        REMAINING_PAIR_UNIVERSE - cumulative == FINAL_REMAINING_COUNT,
        "Stage70 final remaining-pair count drift",
    )
    return tuple(rows)


def _table_entries(record: Mapping[str, object], context: str) -> tuple[int, tuple[int, ...]]:
    order = record.get("order")
    entries = record.get("entries")
    _require(
        isinstance(order, int) and not isinstance(order, bool) and 5 <= order <= 255,
        f"{context}: invalid Stage50 candidate order",
    )
    _require(isinstance(entries, (list, tuple)), f"{context}: entries must be a list or tuple")
    values = tuple(entries)
    _require(len(values) == order * order, f"{context}: table is not square")
    _require(
        all(isinstance(value, int) and not isinstance(value, bool) for value in values),
        f"{context}: table entries must be integers",
    )
    _require(all(0 <= value < order for value in values), f"{context}: table entry outside carrier")
    return order, values


def index_candidate_table_records(
    records: Iterable[Mapping[str, object]],
) -> dict[str, CandidateTableRecord]:
    """Index 3,535 validated Stage50 table records by unprefixed historical hash."""

    by_historical_id: dict[str, CandidateTableRecord] = {}
    seen_canonical_ids: set[str] = set()
    for position, record in enumerate(records):
        context = f"Stage50 candidate record {position}"
        _require(isinstance(record, Mapping), f"{context}: record must be a mapping")
        order, entries = _table_entries(record, context)
        raw = bytes((order, *entries))
        expected_canonical = "sha256:" + hashlib.sha256(raw).hexdigest()
        canonical = record.get("table_id")
        _require(
            isinstance(canonical, str) and bool(_TABLE_ID_RE.fullmatch(canonical)),
            f"{context}: invalid canonical table_id",
        )
        _require(canonical == expected_canonical, f"{context}: canonical table_id drift")

        nested = [
            list(entries[offset : offset + order])
            for offset in range(0, len(entries), order)
        ]
        compact = json.dumps(
            nested,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        expected_historical = hashlib.sha256(compact).hexdigest()
        identifiers = record.get("identifiers")
        _require(
            isinstance(identifiers, Sequence)
            and not isinstance(identifiers, (str, bytes, bytearray)),
            f"{context}: identifiers must be a sequence",
        )
        aliases = [
            identifier.get("value")
            for identifier in identifiers
            if isinstance(identifier, Mapping)
            and identifier.get("scheme") == HISTORICAL_ID_SCHEME
        ]
        _require(len(aliases) == 1, f"{context}: expected one historical identifier")
        historical = aliases[0]
        _require(
            isinstance(historical, str) and bool(_TABLE_ID_RE.fullmatch(historical)),
            f"{context}: invalid historical identifier",
        )
        historical_digest = historical.removeprefix("sha256:")
        _require(
            historical_digest == expected_historical,
            f"{context}: historical compact-JSON digest drift",
        )
        _require(canonical not in seen_canonical_ids, f"{context}: duplicate canonical table_id")
        _require(
            historical_digest not in by_historical_id,
            f"{context}: duplicate historical model_sha256",
        )
        seen_canonical_ids.add(canonical)
        by_historical_id[historical_digest] = CandidateTableRecord(
            candidate_position=position,
            canonical_table_id=canonical,
            historical_model_sha256=historical_digest,
            order=order,
            record=record,
        )

    _require(
        len(by_historical_id) == MODEL_COUNT,
        f"Stage50 candidate input has {len(by_historical_id)} records, expected {MODEL_COUNT}",
    )
    return by_historical_id


def derive_positive_marginal_core(
    individual_csv: CsvSource,
    deduplicated_csv: CsvSource,
    candidate_records: Iterable[Mapping[str, object]],
    *,
    individual_sha256: str | None = INDIVIDUAL_CSV_SHA256,
    deduplicated_sha256: str | None = DEDUPLICATED_CSV_SHA256,
) -> Stage70Result:
    """Validate both rankings, join Stage50 candidates, and derive Stage70.

    ``core_records`` is ordered by the historical coverage ranking after filtering
    for strictly positive marginal coverage.  ``removal_metadata`` contains the
    complementary 2,065 zero-marginal candidates in that same ranking order.
    The returned ``scores`` can be streamed through
    :meth:`Stage70Result.normalized_coverage_rows` to write
    ``DEDUPLICATED_HEADER + canonical_table_id`` without choosing a repository
    path or compression format here.
    """

    individual_rows = load_individual_coverage(
        individual_csv,
        expected_sha256=individual_sha256,
    )
    deduplicated_rows = load_deduplicated_coverage(
        deduplicated_csv,
        expected_sha256=deduplicated_sha256,
    )
    candidates = index_candidate_table_records(candidate_records)
    _require(
        len(individual_rows) == len(deduplicated_rows) == len(candidates),
        "Stage70 input cardinalities disagree",
    )

    scores: list[MappedCoverageScore] = []
    core_records: list[Mapping[str, object]] = []
    positive_decisions: list[SelectionDecision] = []
    removal_metadata: list[SelectionDecision] = []
    used_historical_ids: set[str] = set()

    for individual, deduplicated in zip(individual_rows, deduplicated_rows):
        context = f"Stage70 coverage rank {individual.coverage_rank}"
        _require(
            individual.common_identity_and_counts()
            == deduplicated.common_identity_and_counts(),
            f"{context}: individual/deduplicated row mismatch",
        )
        candidate = candidates.get(individual.model_sha256)
        _require(candidate is not None, f"{context}: model_sha256 absent from Stage50")
        _require(candidate.order == individual.order, f"{context}: candidate order mismatch")
        _require(
            individual.model_sha256 not in used_historical_ids,
            f"{context}: candidate joined more than once",
        )
        used_historical_ids.add(individual.model_sha256)
        score = MappedCoverageScore(
            individual=individual,
            deduplicated=deduplicated,
            candidate=candidate,
        )
        scores.append(score)
        positive = deduplicated.new_unique_remaining_pair_count > 0
        decision = SelectionDecision(
            action="retain" if positive else "remove",
            reason_code=POSITIVE_REASON_CODE if positive else ZERO_REASON_CODE,
            coverage_rank=individual.coverage_rank,
            model_index=individual.model_index,
            candidate_position=candidate.candidate_position,
            canonical_table_id=candidate.canonical_table_id,
            historical_model_sha256=individual.model_sha256,
            order=individual.order,
            remaining_pair_coverage_count=(
                individual.remaining_pair_coverage_count
            ),
            new_unique_remaining_pair_count=(
                deduplicated.new_unique_remaining_pair_count
            ),
            overlap_remaining_pair_count=(
                deduplicated.overlap_remaining_pair_count
            ),
            cumulative_unique_remaining_pair_count=(
                deduplicated.cumulative_unique_remaining_pair_count
            ),
        )
        if positive:
            core_records.append(candidate.record)
            positive_decisions.append(decision)
        else:
            removal_metadata.append(decision)

    _require(
        used_historical_ids == set(candidates),
        "Stage70 coverage ranking is not an exact permutation of Stage50 candidates",
    )
    _require(len(core_records) == POSITIVE_MARGINAL_COUNT, "Stage70 core size drift")
    _require(len(removal_metadata) == ZERO_MARGINAL_COUNT, "Stage70 removal size drift")
    _require(
        len({decision.canonical_table_id for decision in positive_decisions})
        == POSITIVE_MARGINAL_COUNT,
        "Stage70 core contains duplicate canonical tables",
    )

    summary = Stage70Summary(
        candidate_count=MODEL_COUNT,
        positive_marginal_count=POSITIVE_MARGINAL_COUNT,
        zero_marginal_count=ZERO_MARGINAL_COUNT,
        final_union_count=FINAL_UNION_COUNT,
        remaining_uncovered_count=FINAL_REMAINING_COUNT,
    )
    return Stage70Result(
        scores=tuple(scores),
        core_records=tuple(core_records),
        positive_decisions=tuple(positive_decisions),
        removal_metadata=tuple(removal_metadata),
        summary=summary,
    )


__all__ = [
    "CandidateTableRecord",
    "DEDUPLICATED_CSV_SHA256",
    "DEDUPLICATED_HEADER",
    "DeduplicatedCoverageRow",
    "FINAL_REMAINING_COUNT",
    "FINAL_UNION_COUNT",
    "INDIVIDUAL_CSV_SHA256",
    "INDIVIDUAL_HEADER",
    "IndividualCoverageRow",
    "MODEL_COUNT",
    "MappedCoverageScore",
    "NORMALIZED_COVERAGE_HEADER",
    "POSITIVE_MARGINAL_COUNT",
    "REMAINING_PAIR_UNIVERSE",
    "SelectionDecision",
    "Stage70Result",
    "Stage70Summary",
    "Stage70Error",
    "Stage70ValidationError",
    "ZERO_MARGINAL_COUNT",
    "derive_positive_marginal_core",
    "index_candidate_table_records",
    "load_deduplicated_coverage",
    "load_individual_coverage",
]
