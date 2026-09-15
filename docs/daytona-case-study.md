# Daytona GTP telemetry case study

## Objective

Demonstrate a reproducible workflow for moving from two Mu-exported MoTeC logs to an engineering comparison: select each session's quickest completed lap, align both laps by distance, quantify the time movement through manual track segments, and inspect the associated driver inputs.

## Data and controls

Both runs used the Cadillac V-Series.R GTP, Daytona's road course, and the same baseline setup. They were recorded in separate sessions, so this is a driver-analysis example—not a controlled vehicle-performance experiment.

| Variable at selected-lap start | Author | Reference |
|---|---:|---:|
| Source-session fastest completed lap | 11 | 9 |
| Official lap time | 1:34.491 | 1:34.687 |
| Air temperature | 22.55 °C | 21.81 °C |
| Track temperature | 24.44 °C | 22.78 °C |
| Samples in public lap | 5,669 | 5,681 |
| Sample rate | 60 Hz | 60 Hz |

The public logs use role labels, remove identifying session metadata, exclude adjacent lap fragments, and retain only 11 analysis channels. The full sessions are not included. See [`sample_manifest.json`](../examples/sample_manifest.json) for the machine-readable record.

## Method

1. Read `LapBestLap` and `LapBestLapTime` to identify each session's official best lap.
2. Reject edge fragments unless `LapDistPct` covers essentially the complete 0–100% range.
3. Extract the selected lap from the MoTeC-trimmed source and normalize its time origin and distance origin.
4. Resample both laps to 2,000 equally spaced distance points.
5. Define Daytona's turns with the meter ranges in [`track_segments.json`](../track_segments.json).
6. Calculate segment time as Author minus Reference. Negative values mean the Author traversed that range faster.

The case-study script and all published results are reproducible from the repository:

```bash
python examples/generate_daytona_case_study.py
```

## Results

The Author lap was **0.196 s quicker** overall in these recordings.

![Speed, throttle, and brake traces](images/trace-comparison.png)

The largest corner-level gain appeared in Turn 3: **−0.270 s**. Over that manually defined range, the Author averaged 101.4 km/h versus 98.6 km/h and showed lower mean brake application. This suggests speed retention through the range is worth investigating in the raw trace; the averages alone do not prove a specific technique caused the gain.

The largest corner-level loss was Turn 4 at **+0.039 s**. The Reference averaged 120.6 km/h versus 119.8 km/h and carried more mean throttle through the range. Turns 7 and 8 also favored the Reference by 0.011 s and 0.025 s respectively.

![Corner-segment delta](images/segment-delta.png)

The final Turn 8-to-Turn 1 straight favored the Reference by **0.212 s**, with a 3.1 km/h higher average speed. That is a useful review target, but it could reflect the preceding exit, energy deployment, fuel/tire state, or environmental differences rather than one isolated driver input.

## Consistency view

For a readable representative-pace view, the chart includes completed laps within 102% of each session's best. The complete derived lap-time table remains available in [`daytona_lap_times.csv`](../examples/daytona_lap_times.csv).

| Role | Representative laps | Mean | Median | Population σ |
|---|---:|---:|---:|---:|
| Author | 21 | 1:34.977 | 1:34.883 | 0.376 s |
| Reference | 9 | 1:35.025 | 1:34.824 | 0.483 s |

![Representative stint consistency](images/lap-consistency.png)

This filter removes slow completed laps likely affected by traffic, incidents, or non-representative running. It is stated explicitly so the chart is not mistaken for an unfiltered whole-stint statistic.

## Limits on interpretation

- The sessions had different temperatures and may also differ in fuel, tire state, traffic, and driver intent.
- Manual segments are convenient and auditable but not automatically validated against track geometry.
- Distance interpolation can shift sharp events slightly and does not account for alternate racing lines.
- Segment deltas use sampled boundaries, so their sum can differ from the finish-line delta by a few milliseconds.
- Mean throttle, brake, and speed are screening metrics; detailed conclusions require trace-level review.

Within those limits, the workflow does what it is intended to do: reduce two large logs to concrete regions for a driver or engineer to inspect next.
