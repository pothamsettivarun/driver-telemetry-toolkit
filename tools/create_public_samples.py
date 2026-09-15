"""Create anonymized, single-lap public samples from private session logs.

This maintainer utility deliberately selects iRacing's officially reported
quickest completed lap from each source session. The full source files are
read locally and are never copied into the repository.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ldparser import ldData  # noqa: E402
from main import compute_lap_summaries, load_ld_core  # noqa: E402


CHANNEL_METADATA = {
    "SessionTime": ("SessTime", "s"),
    "Speed": ("Speed", "m/s"),
    "Throttle Position": ("Throttle", "%"),
    "Brake Pedal Position": ("Brake", "%"),
    "Lap": ("Lap", "lap"),
    "Lap Number": ("LapNum", "lap"),
    "LapBestLap": ("BestLap", "lap"),
    "LapBestLapTime": ("BestTime", "s"),
    "LapDistPct": ("LapPct", "%"),
    "LapDist": ("LapDist", "m"),
    "LatAccel": ("LatAccel", "m/s2"),
}


def _best_completed_lap(source: Path) -> tuple[ldData, dict[str, list[float]], list[dict[str, Any]], dict[str, Any]]:
    log, data = load_ld_core(str(source))
    laps, best_lap_number, _ = compute_lap_summaries(data)
    best = next(
        (
            lap
            for lap in laps
            if lap["lap_num"] == best_lap_number and not lap["is_incomplete"]
        ),
        None,
    )
    if best is None:
        raise ValueError(f"No completed fastest lap could be identified in {source}")
    return log, data, laps, best


def _normalized_trace(values: list[float], start: int, end: int) -> np.ndarray:
    trace = np.asarray(values[start : end + 1], dtype=float)
    if trace.size < 2 or not np.all(np.isfinite(trace)):
        raise ValueError("Selected lap contains an invalid trace")
    return trace


def _write_sample(
    role: str,
    source: Path,
    destination: Path,
) -> dict[str, Any]:
    log, data, laps, best = _best_completed_lap(source)
    start = int(best["start_idx"])
    end = int(best["end_idx"])
    official_time = float(best["lap_time"])

    session_time = _normalized_trace(data["time"], start, end)
    session_time -= session_time[0]
    if session_time[-1] <= 0:
        raise ValueError("Selected lap has no positive elapsed time")
    session_time *= official_time / session_time[-1]

    distance = _normalized_trace(data["lap_dist"], start, end)
    distance = np.maximum.accumulate(distance - distance[0])
    if distance[-1] <= 0:
        raise ValueError("Selected lap has no positive distance")

    distance_pct = 100.0 * distance / distance[-1]
    sample_count = len(session_time)
    frame = pd.DataFrame(
        {
            "SessionTime": session_time,
            "Speed": _normalized_trace(data["speed"], start, end),
            "Throttle Position": _normalized_trace(data["throttle"], start, end),
            "Brake Pedal Position": _normalized_trace(data["brake"], start, end),
            "Lap": np.ones(sample_count),
            "Lap Number": np.ones(sample_count),
            "LapBestLap": np.ones(sample_count),
            "LapBestLapTime": np.full(sample_count, official_time),
            "LapDistPct": distance_pct,
            "LapDist": distance,
            "LatAccel": _normalized_trace(data["lat_acc"], start, end),
        }
    )

    public_log = ldData.frompd(frame)
    public_log.head.driver = f"{role} Driver"
    public_log.head.vehicleid = "Cadillac V-Series.R GTP"
    public_log.head.venue = "daytona 2011 road"
    public_log.head.datetime = dt.datetime(2025, 1, 1, 12, 0, 0)
    public_log.head.short_comment = "Anonymized fastest-lap sample"
    public_log.head.event.name = "Daytona telemetry case study"
    public_log.head.event.session = "Public sample"
    public_log.head.event.comment = "Published with driver permission"

    for channel in public_log.channs:
        short_name, unit = CHANNEL_METADATA[channel.name]
        channel.freq = 60
        channel.short_name = short_name
        channel.unit = unit

    destination.parent.mkdir(parents=True, exist_ok=True)
    public_log.write(str(destination))

    # Read the generated log back through the production path. This catches
    # malformed pointers, missing channels, and accidental incomplete laps.
    checked_log, checked_data = load_ld_core(str(destination))
    checked_laps, checked_best, _ = compute_lap_summaries(checked_data)
    checked = next((lap for lap in checked_laps if lap["lap_num"] == checked_best), None)
    if checked is None or checked["is_incomplete"]:
        raise RuntimeError(f"Generated sample did not contain a completed lap: {destination}")
    if abs(float(checked["lap_time"]) - official_time) > 0.001:
        raise RuntimeError(f"Generated sample did not preserve official lap time: {destination}")
    if checked_log.head.driver not in {"Author Driver", "Reference Driver"}:
        raise RuntimeError(f"Generated sample header was not anonymized: {destination}")

    def channel_value(name: str) -> float | None:
        if name not in list(log):
            return None
        values = log[name].data
        if start >= len(values):
            return None
        value = float(values[start])
        return value if np.isfinite(value) else None

    return {
        "role": role,
        "file": destination.name,
        "source_fastest_completed_lap": int(best["lap_num"]),
        "official_lap_time_s": official_time,
        "samples": sample_count,
        "sample_rate_hz": 60,
        "lap_length_m": float(distance[-1]),
        "completed_laps_in_source_excerpt": sum(not lap["is_incomplete"] for lap in laps),
        "conditions": {
            "air_temperature_c": channel_value("AirTemp"),
            "track_temperature_c": channel_value("TrackTemp"),
        },
    }


def _lap_rows(source: Path, role: str) -> list[dict[str, Any]]:
    _, data = load_ld_core(str(source))
    laps, best_lap_number, _ = compute_lap_summaries(data)
    return [
        {
            "driver_role": role,
            "lap_number": int(lap["lap_num"]),
            "lap_time_s": float(lap["lap_time"]),
            "is_fastest": lap["lap_num"] == best_lap_number,
        }
        for lap in laps
        if not lap["is_incomplete"]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--author", type=Path, required=True, help="Author's MoTeC-trimmed .ld excerpt")
    parser.add_argument("--reference", type=Path, required=True, help="Reference MoTeC-trimmed .ld excerpt")
    parser.add_argument(
        "--author-stint",
        type=Path,
        help="Optional full stint used only for the anonymized consistency CSV",
    )
    parser.add_argument(
        "--reference-stint",
        type=Path,
        help="Optional full stint used only for the anonymized consistency CSV",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT,
        help="Repository root that will receive examples/data and metadata",
    )
    args = parser.parse_args()

    output_root = args.output_root.resolve()
    author = _write_sample(
        "Author", args.author.resolve(), output_root / "examples/data/author_fastest_lap.ld"
    )
    reference = _write_sample(
        "Reference",
        args.reference.resolve(),
        output_root / "examples/data/reference_fastest_lap.ld",
    )

    manifest = {
        "schema_version": 1,
        "selection": "Official quickest completed lap from each source session",
        "track": "Daytona International Speedway road course",
        "vehicle": "Cadillac V-Series.R GTP",
        "setup_context": "Same vehicle, track, and setup; separate sessions with different conditions",
        "privacy": (
            "Each public log contains one anonymized lap. Full sessions are excluded. "
            "Both drivers authorized publication of these samples."
        ),
        "samples": {
            "author": author,
            "reference": reference,
        },
    }
    manifest_path = output_root / "examples/sample_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    lap_times_path = output_root / "examples/daytona_lap_times.csv"
    with lap_times_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["driver_role", "lap_number", "lap_time_s", "is_fastest"],
            lineterminator="\n",
        )
        writer.writeheader()
        author_stint = (args.author_stint or args.author).resolve()
        reference_stint = (args.reference_stint or args.reference).resolve()
        writer.writerows(
            _lap_rows(author_stint, "Author")
            + _lap_rows(reference_stint, "Reference")
        )

    print(f"Wrote {manifest_path}")
    print(f"Wrote {lap_times_path}")
    print(
        "Selected source laps: "
        f"Author {author['source_fastest_completed_lap']} ({author['official_lap_time_s']:.6f}s), "
        f"Reference {reference['source_fastest_completed_lap']} "
        f"({reference['official_lap_time_s']:.6f}s)"
    )


if __name__ == "__main__":
    main()
