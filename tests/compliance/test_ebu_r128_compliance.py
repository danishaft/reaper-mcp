"""Opt-in checks against the locally supplied EBU Loudness Test Set v5.0.

Set ``REAPER_MCP_EBU_TEST_SET_DIR`` to an extracted test-set directory and
``REAPER_MCP_EBU_TEST_TERMS_ACCEPTED=true`` after reviewing the EBU terms.
The licensed test sequences must never be copied into this repository.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from reaper_mcp.models.audio_measurement import AudioMeasurementRequest
from reaper_mcp.services.audio_measurement_backend import FfmpegEbur128Backend


@dataclass(frozen=True)
class ComplianceCase:
    """One selected EBU Tech 3341 v4.0 minimum-requirements check."""

    case_number: int
    metric: str
    expected: float
    lower_tolerance: float
    upper_tolerance: float


LOUDNESS_CASES = (
    ComplianceCase(1, "integrated_lufs", -23.0, 0.1, 0.1),
    ComplianceCase(1, "momentary_max_lufs", -23.0, 0.1, 0.1),
    ComplianceCase(1, "short_term_max_lufs", -23.0, 0.1, 0.1),
    ComplianceCase(2, "integrated_lufs", -33.0, 0.1, 0.1),
    ComplianceCase(2, "momentary_max_lufs", -33.0, 0.1, 0.1),
    ComplianceCase(2, "short_term_max_lufs", -33.0, 0.1, 0.1),
    *(ComplianceCase(case, "integrated_lufs", -23.0, 0.1, 0.1) for case in range(3, 9)),
)

TRUE_PEAK_CASES = (
    *(ComplianceCase(case, "true_peak_dbtp", -6.0, 0.4, 0.2) for case in range(15, 19)),
    ComplianceCase(19, "true_peak_dbtp", 3.0, 0.4, 0.2),
    *(ComplianceCase(case, "true_peak_dbtp", 0.0, 0.4, 0.2) for case in range(20, 24)),
)


def _test_set_root() -> Path:
    configured = os.environ.get("REAPER_MCP_EBU_TEST_SET_DIR")
    accepted = os.environ.get("REAPER_MCP_EBU_TEST_TERMS_ACCEPTED") == "true"
    if not configured or not accepted:
        pytest.skip(
            "Set the EBU test directory and explicitly accept its terms to run."
        )
    root = Path(configured).expanduser().resolve()
    if not root.is_dir():
        pytest.fail(f"EBU test-set directory does not exist: {root}")
    return root


def _case_files(root: Path, case_number: int) -> list[Path]:
    revision = r"(?:[-_]2011)?" if case_number == 8 else ""
    pattern = re.compile(
        rf"(?:^|[-_])3341{revision}[-_]{case_number}(?:[-_.]|$)",
        re.IGNORECASE,
    )
    matches = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".wav", ".flac"}
        and pattern.search(path.stem)
    ]
    if not matches:
        pytest.fail(f"No EBU Tech 3341 case {case_number} audio file was found.")
    return sorted(matches)


async def _run_cases(cases: tuple[ComplianceCase, ...]) -> None:
    root = _test_set_root()
    backend = FfmpegEbur128Backend(timeout_seconds=300.0)
    measurements: dict[Path, object] = {}
    for case in cases:
        for path in _case_files(root, case.case_number):
            if path not in measurements:
                source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
                measurements[path] = await backend.measure(
                    AudioMeasurementRequest(audio_path=path),
                    source_sha256,
                )
            result = measurements[path]
            container = (
                result.peaks if case.metric == "true_peak_dbtp" else result.loudness
            )
            actual = getattr(container, case.metric)
            assert actual is not None
            assert (
                case.expected - case.lower_tolerance
                <= actual
                <= case.expected + case.upper_tolerance
            ), f"EBU case {case.case_number} {path.name}: {case.metric}={actual}"


async def test_selected_ebu_tech_3341_loudness_cases() -> None:
    await _run_cases(LOUDNESS_CASES)


async def test_selected_ebu_tech_3341_true_peak_cases() -> None:
    await _run_cases(TRUE_PEAK_CASES)
