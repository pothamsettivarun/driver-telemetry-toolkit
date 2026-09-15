"""Regenerate the checked-in Daytona case-study outputs."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import (  # noqa: E402
    build_profile_for_lap,
    compute_lap_summaries,
    enrich_segments_with_stats,
    load_ld_core,
    load_track_segments_for,
    resample_profiles,
    segment_deltas_manual,
)
from plotting import (  # noqa: E402
    plot_lap_consistency,
    plot_segment_deltas,
    plot_trace_comparison,
)


def _fastest_profile(path: Path):
    log, data = load_ld_core(str(path))
    laps, best_number, _ = compute_lap_summaries(data)
    best = next(lap for lap in laps if lap["lap_num"] == best_number)
    profile = build_profile_for_lap(data, best["start_idx"], best["end_idx"])
    return log, best, profile


def main() -> None:
    data_dir = PROJECT_ROOT / "examples/data"
    images_dir = PROJECT_ROOT / "docs/images"

    author_log, author_lap, author_profile = _fastest_profile(data_dir / "author_fastest_lap.ld")
    _, reference_lap, reference_profile = _fastest_profile(data_dir / "reference_fastest_lap.ld")

    distance, cumulative_delta, profiles = resample_profiles(
        author_profile, reference_profile, n_grid=2000
    )
    turns = load_track_segments_for(author_log.head.venue)
    if not turns:
        raise RuntimeError(f"No manual segments found for {author_log.head.venue!r}")

    segments = segment_deltas_manual(
        distance,
        cumulative_delta,
        profiles["me"][0],
        profiles["ref"][0],
        author_profile["lap_length_m"],
        turns,
    )
    segments = enrich_segments_with_stats(
        segments,
        profiles["me"][1],
        profiles["ref"][1],
        profiles["me"][2],
        profiles["ref"][2],
        profiles["me"][3],
        profiles["ref"][3],
    )

    with (PROJECT_ROOT / "examples/daytona_lap_times.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        lap_rows = list(csv.DictReader(handle))

    plot_lap_consistency(lap_rows, images_dir / "lap-consistency.png")
    plot_segment_deltas(segments, images_dir / "segment-delta.png")
    plot_trace_comparison(
        distance,
        profiles,
        author_profile["lap_length_m"],
        turns,
        images_dir / "trace-comparison.png",
    )

    results = {
        "comparison_sign_convention": "positive means Author slower than Reference",
        "author_fastest_lap_s": float(author_lap["lap_time"]),
        "reference_fastest_lap_s": float(reference_lap["lap_time"]),
        "author_minus_reference_s": float(author_lap["lap_time"] - reference_lap["lap_time"]),
        "manual_segments": [
            {
                "name": segment["name"],
                "delta_s": segment["delta"],
                "author_average_speed_kmh": segment["speed_me"] * 3.6,
                "reference_average_speed_kmh": segment["speed_ref"] * 3.6,
                "author_average_throttle_pct": segment["thr_me"],
                "reference_average_throttle_pct": segment["thr_ref"],
                "author_average_brake_pct": segment["br_me"],
                "reference_average_brake_pct": segment["br_ref"],
            }
            for segment in segments
        ],
    }
    results_path = PROJECT_ROOT / "examples/daytona_results.json"
    results_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote three plots to {images_dir}")
    print(f"Wrote {results_path}")


if __name__ == "__main__":
    main()

