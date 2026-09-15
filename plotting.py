"""Static, portfolio-ready plots for the telemetry analysis examples."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter


BACKGROUND = "#0B1020"
PANEL = "#11182B"
TEXT = "#F4F7FB"
MUTED = "#AAB4C7"
GRID = "#34405B"
AUTHOR = "#29C5F6"
REFERENCE = "#FFB547"
GAIN = "#2DD4BF"
LOSS = "#FF647C"


def _lap_time_label(seconds: float, _position: int | None = None) -> str:
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:04.1f}"


def _save(fig: plt.Figure, output: str | Path) -> None:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=160, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def _apply_axis_style(axis: plt.Axes) -> None:
    axis.set_facecolor(PANEL)
    axis.tick_params(colors=MUTED)
    axis.xaxis.label.set_color(MUTED)
    axis.yaxis.label.set_color(MUTED)
    axis.title.set_color(TEXT)
    axis.grid(True, color=GRID, alpha=0.45, linewidth=0.8)
    for spine in axis.spines.values():
        spine.set_color(GRID)


def plot_lap_consistency(
    lap_rows: Sequence[Mapping[str, object]],
    output: str | Path,
) -> None:
    """Plot completed-lap pace across the two source stints."""
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 10}):
        fig, axis = plt.subplots(figsize=(12, 6.75), facecolor=BACKGROUND)
        _apply_axis_style(axis)

        for role, color in (("Author", AUTHOR), ("Reference", REFERENCE)):
            all_rows = [row for row in lap_rows if row["driver_role"] == role]
            fastest = min(float(row["lap_time_s"]) for row in all_rows)
            rows = [
                row for row in all_rows
                if float(row["lap_time_s"]) <= fastest * 1.02
            ]
            laps = np.asarray([int(row["lap_number"]) for row in rows])
            times = np.asarray([float(row["lap_time_s"]) for row in rows])
            axis.plot(laps, times, color=color, linewidth=1.8, alpha=0.8)
            axis.scatter(laps, times, color=color, s=34, edgecolor=BACKGROUND, linewidth=0.7,
                         label=f"{role} · n={len(times)} · σ {np.std(times):.3f}s")
            fastest_index = int(np.argmin(times))
            axis.scatter(
                laps[fastest_index], times[fastest_index], s=150, marker="*",
                color=color, edgecolor=TEXT, linewidth=0.8, zorder=5,
            )
            axis.annotate(
                f"{times[fastest_index]:.3f}s",
                (laps[fastest_index], times[fastest_index]),
                xytext=(8, -18), textcoords="offset points", color=color,
                fontsize=10, fontweight="bold",
            )

        axis.set_title(
            "Daytona stint consistency", loc="left", fontsize=19,
            fontweight="bold", pad=16, color=TEXT,
        )
        axis.text(
            0.0, 1.01,
            "Representative completed laps within 102% of each session best · star = quickest",
            transform=axis.transAxes, color=MUTED, fontsize=10,
        )
        axis.set_xlabel("Source-session lap number")
        axis.set_ylabel("Lap time")
        axis.yaxis.set_major_formatter(FuncFormatter(_lap_time_label))
        axis.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, loc="upper right")
        fig.text(
            0.01, 0.01, "Anonymized Mu/iRacing telemetry · separate sessions",
            color=MUTED, fontsize=8,
        )
        fig.tight_layout(rect=(0, 0.025, 1, 1))
        _save(fig, output)


def plot_segment_deltas(
    segments: Sequence[Mapping[str, object]],
    output: str | Path,
) -> None:
    """Plot author-minus-reference time for manually defined turns."""
    turns = [segment for segment in segments if str(segment["name"]).startswith("Turn")]
    names = [str(segment["name"]) for segment in turns]
    deltas = np.asarray([float(segment["delta"]) for segment in turns])
    colors = [LOSS if value > 0 else GAIN for value in deltas]

    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 10}):
        fig, axis = plt.subplots(figsize=(12, 6.75), facecolor=BACKGROUND)
        _apply_axis_style(axis)
        positions = np.arange(len(names))
        bars = axis.barh(positions, deltas, color=colors, height=0.62)
        axis.axvline(0, color=TEXT, linewidth=1.0, alpha=0.8)
        axis.set_yticks(positions, names)
        axis.invert_yaxis()
        axis.set_xlabel("Time delta (s) · Author − Reference")
        axis.set_title(
            "Daytona corner delta", loc="left", fontsize=19,
            fontweight="bold", pad=16, color=TEXT,
        )
        axis.text(
            0.0, 1.01, "Negative = Author faster · positive = Reference faster",
            transform=axis.transAxes, color=MUTED, fontsize=10,
        )
        axis.grid(axis="y", visible=False)
        axis.grid(axis="x", color=GRID, alpha=0.5)
        for bar, value in zip(bars, deltas):
            offset = 4 if value >= 0 else -4
            alignment = "left" if value >= 0 else "right"
            axis.annotate(
                f"{value:+.3f}",
                (value, bar.get_y() + bar.get_height() / 2),
                xytext=(offset, 0), textcoords="offset points",
                va="center", ha=alignment, color=TEXT, fontsize=9,
            )
        fig.text(
            0.01, 0.01, "Manual distance ranges in track_segments.json · distance-normalized comparison",
            color=MUTED, fontsize=8,
        )
        fig.tight_layout(rect=(0, 0.025, 1, 1))
        _save(fig, output)


def plot_trace_comparison(
    distance_fraction: np.ndarray,
    profiles: Mapping[str, tuple[np.ndarray, ...]],
    lap_length_m: float,
    turns: Sequence[Mapping[str, object]],
    output: str | Path,
) -> None:
    """Plot speed, throttle, and brake traces over lap distance."""
    distance_km = distance_fraction * lap_length_m / 1000.0
    _, author_speed, author_throttle, author_brake, _ = profiles["me"]
    _, reference_speed, reference_throttle, reference_brake, _ = profiles["ref"]

    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 10}):
        fig, axes = plt.subplots(
            3, 1, figsize=(12, 7.2), sharex=True, facecolor=BACKGROUND,
            gridspec_kw={"height_ratios": [2.0, 1.0, 1.0], "hspace": 0.10},
        )
        for axis in axes:
            _apply_axis_style(axis)
            for turn in turns:
                start = float(turn["start_m"]) / 1000.0
                end = float(turn["end_m"]) / 1000.0
                axis.axvspan(start, end, color="#7783A0", alpha=0.09, linewidth=0)

        axes[0].plot(distance_km, author_speed * 3.6, color=AUTHOR, linewidth=1.45, label="Author")
        axes[0].plot(distance_km, reference_speed * 3.6, color=REFERENCE, linewidth=1.25,
                     alpha=0.92, label="Reference")
        axes[0].set_ylabel("Speed (km/h)")
        axes[0].legend(facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, loc="lower right")
        fig.suptitle(
            "Fastest-lap trace comparison", x=0.09, y=0.975, ha="left",
            fontsize=19, fontweight="bold", color=TEXT,
        )
        fig.text(
            0.09, 0.935, "Cadillac V-Series.R GTP · Daytona road course",
            color=MUTED, fontsize=10,
        )

        axes[1].plot(distance_km, author_throttle, color=AUTHOR, linewidth=1.25)
        axes[1].plot(distance_km, reference_throttle, color=REFERENCE, linewidth=1.15, alpha=0.92)
        axes[1].set_ylabel("Throttle (%)")
        axes[1].set_ylim(-3, 103)

        axes[2].plot(distance_km, author_brake, color=AUTHOR, linewidth=1.25)
        axes[2].plot(distance_km, reference_brake, color=REFERENCE, linewidth=1.15, alpha=0.92)
        axes[2].set_ylabel("Brake (%)")
        axes[2].set_xlabel("Lap distance (km)")
        axes[2].set_ylim(-3, 103)

        for turn in turns:
            center = (float(turn["start_m"]) + float(turn["end_m"])) / 2000.0
            axes[0].text(
                center, 0.985, f"T{int(turn['turn'])}",
                transform=axes[0].get_xaxis_transform(), ha="center", va="top",
                color=MUTED, fontsize=7,
            )

        fig.text(
            0.01, 0.01, "Quickest completed lap from each session · shaded regions are manual turn ranges",
            color=MUTED, fontsize=8,
        )
        fig.subplots_adjust(left=0.09, right=0.985, top=0.91, bottom=0.09, hspace=0.10)
        _save(fig, output)
