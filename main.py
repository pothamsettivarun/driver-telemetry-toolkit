from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from ldparser import ldData
import json
import os
import sys
from pathlib import Path

# ============================================================
# Helpers for loading .ld and channels
# ============================================================

def _pick_channel(l: ldData,
                  preferred_exact: List[str],
                  fallback_substring: str,
                  required: bool = True) -> Optional[str]:
    """Pick a channel name from ldData by exact name then substring."""
    names = list(l)

    # exact match
    for name in preferred_exact:
        if name in names:
            return name

    fb = fallback_substring.lower()
    for name in names:
        if fb in name.lower():
            return name

    if required:
        raise ValueError(
            f"Could not find channel. Tried exact={preferred_exact}, "
            f"substring='{fallback_substring}'."
        )
    return None

def load_ld_core(filepath: str) -> Tuple[ldData, Dict[str, List[float]]]:
    """
    Load an .ld file with ldparser and return:
      - ldData object
      - data dict with core channels as Python lists:
        time, speed, throttle, brake, lap, lap_number (opt),
        lap_delta_opt (opt), lap_dist_pct (opt), lap_dist (opt),
        lat_acc (opt)
    """
    l = ldData.fromfile(filepath)
    all_names = list(l)

    def chan(name):
        return l[name].data.tolist()

    # Time & speed
    time_name = _pick_channel(l, ["SessionTime"], "time")
    speed_name = _pick_channel(l, ["Speed", "Ground Speed"], "speed")

    # Pedals: use Position channels as requested
    throttle_name = _pick_channel(
        l, ["Throttle Position", "Throttle"], "throttle"
    )
    brake_name = _pick_channel(
        l, ["Brake Pedal Position", "Brake"], "brake"
    )

    # Lap info
    lap_name = _pick_channel(l, ["Lap"], "lap")
    lap_number_name = _pick_channel(l, ["Lap Number"], "lap number",
                                    required=False)
    lap_delta_opt_name = _pick_channel(
        l, ["LapDeltaToSessionOptimalLap"], "LapDeltaToSessionOptimalLap",
        required=False
    )

    # Distance
    lap_dist_pct_name = _pick_channel(
        l, ["LapDistPct"], "LapDistPct", required=False
    )
    lap_dist_name = _pick_channel(
        l, ["LapDist"], "LapDist", required=False
    )

    # Lateral G (for segmentation)
    lat_acc_name = _pick_channel(
        l,
        ["LatAccel", "G Force Lat"],
        "lat",  # just a substring fallback
        required=False,
    )

    print("Using channels:")
    print(f"  Time:             {time_name}")
    print(f"  Speed:            {speed_name}")
    print(f"  Throttle:         {throttle_name}")
    print(f"  Brake:            {brake_name}")
    print(f"  Lap:              {lap_name}")
    if lap_number_name:
        print(f"  Lap Number:       {lap_number_name}")
    if lap_delta_opt_name:
        print(f"  Lap Δ vs Optimal: {lap_delta_opt_name}")
    if lap_dist_pct_name:
        print(f"  LapDistPct:       {lap_dist_pct_name}")
    if lap_dist_name:
        print(f"  LapDist:          {lap_dist_name}")
    if lat_acc_name:
        print(f"  LatAccel:         {lat_acc_name}")

    data: Dict[str, List[float]] = {
        "time": chan(time_name),
        "speed": chan(speed_name),
        "throttle": chan(throttle_name),
        "brake": chan(brake_name),
        "lap": chan(lap_name),
    }

    if lap_number_name:
        data["lap_number"] = chan(lap_number_name)
    if lap_delta_opt_name:
        data["lap_delta_opt"] = chan(lap_delta_opt_name)
    if lap_dist_pct_name:
        data["lap_dist_pct"] = chan(lap_dist_pct_name)
    if lap_dist_name:
        data["lap_dist"] = chan(lap_dist_name)
    if lat_acc_name:
        data["lat_acc"] = chan(lat_acc_name)

    return l, data

# ============================================================
# Session info / conditions
# ============================================================

def _get_env_value(l: ldData, candidates: List[str]) -> Optional[float]:
    names = list(l)
    for c in candidates:
        if c in names:
            arr = l[c].data
            if len(arr) > 0:
                return float(arr[0])
    return None

def show_session_info(l: ldData):
    """Print driver, car, track, and basic conditions."""
    driver = l.head.driver
    car = l.head.vehicleid
    track = l.head.venue

    print("\n=== Session Info ===")
    print(f"Driver: {driver}")
    print(f"Car:    {car}")
    print(f"Track:  {track}")

    air_temp = _get_env_value(l, ["AirTemp"])
    track_temp = _get_env_value(l, ["TrackTemp", "TrackTempCrew"])
    wind_vel = _get_env_value(l, ["WindVel"])
    wind_dir = _get_env_value(l, ["WindDir"])
    humidity = _get_env_value(l, ["RelativeHumidity"])
    wetness = _get_env_value(l, ["TrackWetness"])
    skies = _get_env_value(l, ["Skies"])

    print("Conditions:")
    if air_temp is not None:
        print(f"  Air Temp:   {air_temp:.1f}")
    if track_temp is not None:
        print(f"  Track Temp: {track_temp:.1f}")
    if wind_vel is not None:
        print(f"  Wind Speed: {wind_vel:.1f}")
    if wind_dir is not None:
        print(f"  Wind Dir:   {wind_dir:.1f}")
    if humidity is not None:
        print(f"  Humidity:   {humidity:.1f}")
    if wetness is not None:
        print(f"  TrackWet:   {wetness:.3f}")
    if skies is not None:
        print(f"  Skies:      {skies:.1f}")

# ============================================================
# Core metrics (stint or lap)
# ============================================================

def _normalize_pedal(values: List[float]) -> List[float]:
    if not values:
        return values
    vmax = max(values)
    factor = 100.0 if vmax <= 1.5 else 1.0
    return [v * factor for v in values]

def compute_metrics(data: Dict[str, List[float]]) -> Dict[str, Any]:
    time = data["time"]
    speed = data["speed"]
    throttle_raw = data["throttle"]
    brake_raw = data["brake"]

    n = len(time)
    if n < 2:
        raise ValueError("Not enough samples to compute metrics.")

    throttle = _normalize_pedal(throttle_raw)
    brake = _normalize_pedal(brake_raw)

    avg_throttle = sum(throttle) / n
    avg_brake = sum(brake) / n
    max_speed = max(speed)
    min_speed = min(speed)

    total_abs_delta_throttle = 0.0
    for i in range(1, n):
        total_abs_delta_throttle += abs(throttle[i] - throttle[i - 1])
    throttle_variability = total_abs_delta_throttle / (n - 1)

    mid_throttle_count = sum(1 for th in throttle if 20.0 <= th <= 80.0)
    throttle_mid_fraction = mid_throttle_count / n

    BRAKE_SPIKE_THRESHOLD = 40.0
    brake_spike_count = 0
    for i in range(1, n):
        delta = brake[i] - brake[i - 1]
        if delta > BRAKE_SPIKE_THRESHOLD:
            brake_spike_count += 1

    mid_corner_speeds = []
    for i in range(n):
        th = throttle[i]
        br = brake[i]
        if 5.0 <= th <= 60.0 and br < 10.0:
            mid_corner_speeds.append(speed[i])

    if mid_corner_speeds:
        avg_mid_speed = sum(mid_corner_speeds) / len(mid_corner_speeds)
    else:
        avg_mid_speed = sum(speed) / n

    sorted_speeds = sorted(speed, reverse=True)
    top_count = max(1, int(0.1 * n))
    avg_top_speed = sum(sorted_speeds[:top_count]) / top_count
    mid_corner_speed_ratio = avg_mid_speed / avg_top_speed if avg_top_speed > 0 else 0.0

    return {
        "sample_count": n,
        "avg_throttle": avg_throttle,
        "avg_brake": avg_brake,
        "max_speed": max_speed,
        "min_speed": min_speed,
        "throttle_variability": throttle_variability,
        "throttle_mid_fraction": throttle_mid_fraction,
        "brake_spike_count": brake_spike_count,
        "mid_corner_speed_ratio": mid_corner_speed_ratio,
    }

# ============================================================
# Lap detection and summaries
# ============================================================

def compute_lap_summaries(data: Dict[str, List[float]]):
    """
    Build lap list with:
      lap_num, lap_time, delta_opt, start_idx, end_idx, delta_to_best
    Best lap is chosen ignoring the final lap of the stint.
    """
    time = data["time"]
    lap_vals = data["lap"]
    lap_number_vals = data.get("lap_number")
    lap_delta_opt = data.get("lap_delta_opt")

    n = len(time)
    if n == 0:
        return [], None

    segments = {}
    current_lap = int(round(lap_vals[0]))
    start_idx = 0
    for i in range(1, n):
        lap_i = int(round(lap_vals[i]))
        if lap_i != current_lap:
            segments[current_lap] = (start_idx, i - 1)
            current_lap = lap_i
            start_idx = i
    segments[current_lap] = (start_idx, n - 1)

    laps = []
    for lap_key in sorted(segments.keys()):
        start, end = segments[lap_key]
        if end <= start:
            continue

        lap_time = time[end] - time[start]
        if lap_time <= 0:
            continue

        if lap_number_vals is not None:
            disp_num = int(round(lap_number_vals[start]))
        else:
            disp_num = lap_key

        delta_opt = None
        if lap_delta_opt is not None:
            delta_opt = lap_delta_opt[end]

        laps.append({
            "lap_num": disp_num,
            "lap_time": lap_time,
            "delta_opt": delta_opt,
            "start_idx": start,
            "end_idx": end,
        })

    if not laps:
        return [], None

    last_lap_num = max(l["lap_num"] for l in laps)

    # Best lap chosen ignoring the final lap of the stint
    candidates = [l for l in laps if l["lap_num"] != last_lap_num]
    if not candidates:
        candidates = laps

    best = min(candidates, key=lambda x: x["lap_time"])
    best_time = best["lap_time"]

    for lap in laps:
        lap["is_incomplete"] = (lap["lap_num"] == last_lap_num)
        if lap["is_incomplete"]:
            lap["delta_to_best"] = None
        else:
            lap["delta_to_best"] = lap["lap_time"] - best_time

    # Compute ONE consistent session-optimal lap time from all laps (robust)
    optimal_time = None
    opt_candidates = []
    for lap in laps:
        if lap.get("is_incomplete"):
            continue
        d_opt = lap.get("delta_opt", None)
        if d_opt is None:
            continue
        opt_candidates.append(lap["lap_time"] - float(d_opt))

    if opt_candidates:
        optimal_time = min(opt_candidates)

    # Add a consistent delta_opt_fixed for every lap
    for lap in laps:
        if lap.get("is_incomplete"):
            lap["delta_opt_fixed"] = None
        elif optimal_time is None:
            lap["delta_opt_fixed"] = lap.get("delta_opt", None)
        else:
            lap["delta_opt_fixed"] = lap["lap_time"] - optimal_time

    return laps, best["lap_num"], optimal_time

def format_laptime(sec: float) -> str:
    m = int(sec // 60)
    s = sec - 60 * m
    return f"{m}:{s:06.3f}"

def print_lap_table(laps, best_lap_num, optimal_time=None):
    if optimal_time is not None:
        opt_str = format_laptime(optimal_time)
        print(f"\n  OPT  {opt_str:>9}  {'  N/A ':>7}  {'+0.000':>7}")
        print(" --------------------------------")

    if not laps:
        print("No laps found.")
        return

    print("Lap summary (best lap marked with '*'):")
    print("  Lap    Time      ΔBest    ΔOpt")
    print(" --------------------------------")

    for lap in laps:
        lap_num = lap["lap_num"]
        t = format_laptime(lap["lap_time"])
        d_best = lap["delta_to_best"]
        d_opt = lap.get("delta_opt_fixed", lap.get("delta_opt"))

        if d_best is None:
            d_best_str = "  N/A "
        else:
            d_best_str = f"{d_best:+.3f}" if abs(d_best) > 1e-4 else "+0.000"

        d_opt_str = f"{d_opt:+.3f}" if d_opt is not None else "  N/A"

        marker = "*" if lap_num == best_lap_num else " "
        tag = " (incomplete)" if lap.get("is_incomplete") else ""
        print(f"{marker} {lap_num:3d}  {t:>9}  {d_best_str:>7}  {d_opt_str:>7}{tag}")


def slice_data(data: Dict[str, List[float]], start: int, end: int) -> Dict[str, List[float]]:
    sub = {}
    for key in data.keys():
        sub[key] = data[key][start:end + 1]
    return sub

# ============================================================
# Lap profile + comparison
# ============================================================

def build_profile_for_lap(data: Dict[str, List[float]], start: int, end: int):
    t = np.asarray(data["time"][start:end+1], dtype=float)
    t = t - t[0]

    # Raw distance in meters (preferred) or LapDistPct fallback
    if "lap_dist" in data:
        dist_raw = np.asarray(data["lap_dist"][start:end+1], dtype=float)
    elif "lap_dist_pct" in data:
        dist_raw = np.asarray(data["lap_dist_pct"][start:end+1], dtype=float)
    else:
        # fallback: synthetic linear distance
        dist_raw = np.linspace(0.0, 1.0, num=len(t))

    d_min = dist_raw.min()
    d_max = dist_raw.max()
    lap_length_m = d_max - d_min if d_max > d_min else 1.0

    # Normalized distance 0–1 for resampling
    d = (dist_raw - d_min) / lap_length_m

    speed = np.asarray(data["speed"][start:end+1], dtype=float)
    thr = np.asarray(_normalize_pedal(data["throttle"][start:end+1]), dtype=float)
    brk = np.asarray(_normalize_pedal(data["brake"][start:end+1]), dtype=float)

    if "lat_acc" in data:
        lat = np.asarray(data["lat_acc"][start:end+1], dtype=float)
    else:
        lat = None

    return {
        "d": d,
        "t": t,
        "speed": speed,
        "throttle": thr,
        "brake": brk,
        "lat": lat,
        "dist_m": dist_raw,
        "lap_length_m": lap_length_m,
    }

def resample_profiles(me, ref, n_grid: int = 400):
    d_grid = np.linspace(0.0, 1.0, num=n_grid)

    def interp_profile(p):
        t = np.interp(d_grid, p["d"], p["t"])
        speed = np.interp(d_grid, p["d"], p["speed"])
        thr = np.interp(d_grid, p["d"], p["throttle"])
        brk = np.interp(d_grid, p["d"], p["brake"])
        lat = None
        if p["lat"] is not None:
            lat = np.interp(d_grid, p["d"], p["lat"])
        return t, speed, thr, brk, lat

    t_me, s_me, th_me, br_me, lat_me = interp_profile(me)
    t_ref, s_ref, th_ref, br_ref, lat_ref = interp_profile(ref)

    delta_t = t_me - t_ref  # + = you're slower

    return d_grid, delta_t, {
        "me": (t_me, s_me, th_me, br_me, lat_me),
        "ref": (t_ref, s_ref, th_ref, br_ref, lat_ref),
    }

def prompt_corner_segments(lap_length_m: float):
    """
    Ask the user for corner start/end in meters along the lap.
    Example input: 110-190 (for Turn 1).
    Blank input ends the sequence.
    """
    print(f"\nEnter corner segmentation in meters (0 to {lap_length_m:.1f}).")
    print("Format for each turn: start-end (e.g. 110-190).")
    print("Leave blank and press Enter when you're done.\n")

    turns = []
    idx = 1
    while True:
        raw = input(f"Turn {idx}: ").strip()
        if not raw:
            break

        # normalize unicode dashes to ASCII '-'
        raw_clean = raw.replace("–", "-").replace("—", "-")
        parts = raw_clean.split("-")
        if len(parts) != 2:
            print("  Please use format start-end, e.g. 110-190.")
            continue

        try:
            start_m = float(parts[0])
            end_m = float(parts[1])
        except ValueError:
            print("  Could not parse numbers. Try again.")
            continue

        if not (0.0 <= start_m < end_m <= lap_length_m):
            print(f"  Range must be within 0 and {lap_length_m:.1f} and start < end.")
            continue

        turns.append({"turn": idx, "start_m": start_m, "end_m": end_m})
        idx += 1

    print(f"\n{len(turns)} corners segmented.\n")
    return turns

def build_segments_from_manual(
    turns: List[Dict[str, Any]],
    lap_length_m: float,
    d_grid: np.ndarray,
) -> List[Dict[str, Any]]:
    """
    Build Turn + Straight segments from manual corner list.
    - Turns: use user-defined ranges
    - Straights: fill gaps between corners
    Naming:
      * Straights between Turn i and Turn i+1: Str i-(i+1)
      * Final straight from last corner end to lap end: Str 0-1
    """
    n_grid = len(d_grid)
    if n_grid == 0:
        return []

    # sort by start distance
    turns_sorted = sorted(turns, key=lambda t: t["start_m"])

    segments = []
    prev_end_m = 0.0
    straight_idx = 0
    last_turn_num = 0

    def dist_to_idx(dist_m: float) -> int:
        # map physical meters -> normalized -> index in d_grid
        d_norm = dist_m / lap_length_m
        # clamp
        d_norm = max(0.0, min(1.0, d_norm))
        # left/right depending on use later
        return int(np.searchsorted(d_grid, d_norm, side="left"))

    for t in turns_sorted:
        turn_num = t["turn"]
        start_m = t["start_m"]
        end_m = t["end_m"]

        # Straight BEFORE this turn (gap from prev_end_m to start_m)
        if start_m > prev_end_m:
            s_norm = prev_end_m / lap_length_m
            e_norm = start_m / lap_length_m
            s_idx = int(np.searchsorted(d_grid, s_norm, side="left"))
            e_idx = int(np.searchsorted(d_grid, e_norm, side="right") - 1)
            if e_idx > s_idx:
                if straight_idx == 0:
                    # first straight before Turn 1 – label however you like
                    name = "Str pre-1"
                else:
                    name = f"Str {straight_idx}-{straight_idx+1}"
                segments.append({"name": name, "start": s_idx, "end": e_idx})
                straight_idx += 1

        # The turn itself
        s_norm = start_m / lap_length_m
        e_norm = end_m / lap_length_m
        s_idx = int(np.searchsorted(d_grid, s_norm, side="left"))
        e_idx = int(np.searchsorted(d_grid, e_norm, side="right") - 1)
        if e_idx > s_idx:
            segments.append({
                "name": f"Turn {turn_num}",
                "start": s_idx,
                "end": e_idx,
            })

        prev_end_m = end_m
        last_turn_num = turn_num

    # Final straight: from end of last corner to end of lap
    if prev_end_m < lap_length_m:
        s_norm = prev_end_m / lap_length_m
        s_idx = int(np.searchsorted(d_grid, s_norm, side="left"))
        e_idx = n_grid - 1
        if e_idx > s_idx:
            # per your note: straight from end of final corner = Str 0-1
            segments.append({
                "name": "Str 0-1",
                "start": s_idx,
                "end": e_idx,
            })

    return segments

def segment_deltas_manual(
    d_grid: np.ndarray,
    delta_t: np.ndarray,
    t_me: np.ndarray,
    t_ref: np.ndarray,
    lap_length_m: float,
    turns: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Use manual segments to compute time delta per segment.
    """
    seg_defs = build_segments_from_manual(turns, lap_length_m, d_grid)
    seg_list = []
    for seg in seg_defs:
        s = seg["start"]
        e = seg["end"]
        if e <= s:
            continue
        seg_dt_me = t_me[e] - t_me[s]
        seg_dt_ref = t_ref[e] - t_ref[s]
        seg_delta = seg_dt_me - seg_dt_ref
        seg_list.append({
            "name": seg["name"],
            "delta": seg_delta,
            "start": s,
            "end": e,
        })
    return seg_list

def enrich_segments_with_stats(
    segments: List[Dict[str, Any]],
    s_me: np.ndarray,
    s_ref: np.ndarray,
    th_me: np.ndarray,
    th_ref: np.ndarray,
    br_me: np.ndarray,
    br_ref: np.ndarray,
) -> List[Dict[str, Any]]:
    """
    For each segment, add average speed / throttle / brake for
    you (me) and reference (ref).
    """
    enriched = []
    for seg in segments:
        s = seg["start"]
        e = seg["end"]
        if e <= s:
            continue
        sl = slice(s, e + 1)

        seg_copy = dict(seg)  # shallow copy

        seg_copy["speed_me"] = float(np.mean(s_me[sl]))
        seg_copy["speed_ref"] = float(np.mean(s_ref[sl]))
        seg_copy["thr_me"] = float(np.mean(th_me[sl]))
        seg_copy["thr_ref"] = float(np.mean(th_ref[sl]))
        seg_copy["br_me"] = float(np.mean(br_me[sl]))
        seg_copy["br_ref"] = float(np.mean(br_ref[sl]))

        enriched.append(seg_copy)

    return enriched

def print_segment_details(segments: List[Dict[str, Any]]):
    """
    Pretty-print a segment-by-segment breakdown with
    Δtime, speed, throttle, brake.
    """
    for seg in segments:
        name = seg["name"]
        dt = seg["delta"]
        print(f"\n{name}")
        print(f"     Δtime (s): {dt:+.3f}")
        print(f"     Speed:     you {seg['speed_me']:.1f}, ref {seg['speed_ref']:.1f}")
        print(f"     Throttle:  you {seg['thr_me']:.1f}%, ref {seg['thr_ref']:.1f}%")
        print(f"     Brake:     you {seg['br_me']:.1f}%, ref {seg['br_ref']:.1f}%")

def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent  # EXE folder
    return Path(__file__).resolve().parent           # script folder

SEGMENT_FILE = str(_app_dir() / "track_segments.json")

def load_all_segment_sets() -> Dict[str, Any]:
    """Load all saved segmentations from JSON file."""
    if not os.path.exists(SEGMENT_FILE):
        return {}
    try:
        with open(SEGMENT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # if file is corrupt, just ignore it
        return {}

def save_all_segment_sets(all_segments: Dict[str, Any]) -> None:
    """Save all segmentations to JSON file."""
    with open(SEGMENT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_segments, f, indent=2)

def load_track_segments_for(track_name: str) -> Optional[List[Dict[str, Any]]]:
    """
    Return list of {'turn', 'start_m', 'end_m'} for a track,
    or None if not found.
    """
    all_sets = load_all_segment_sets()
    segs = all_sets.get(track_name)
    if segs is None:
        return None
    # Ensure float conversion (JSON may load as int)
    cleaned = []
    for s in segs:
        cleaned.append({
            "turn": int(s["turn"]),
            "start_m": float(s["start_m"]),
            "end_m": float(s["end_m"]),
        })
    return cleaned

def save_track_segments_for(track_name: str, segments: List[Dict[str, Any]]) -> None:
    all_sets = load_all_segment_sets()
    # store only minimal info
    all_sets[track_name] = [
        {"turn": s["turn"], "start_m": s["start_m"], "end_m": s["end_m"]}
        for s in segments
    ]
    save_all_segment_sets(all_sets)

# ============================================================
# Feedback text
# ============================================================

def generate_feedback(metrics: Dict[str, Any]) -> str:
    lines = []

    mid_frac = metrics["throttle_mid_fraction"]
    thr_var = metrics["throttle_variability"]

    if mid_frac < 0.15 and thr_var > 30.0:
        lines.append(
            "Throttle input is very on/off — mostly 0% or 100%. "
            "Try feeding the throttle in more gradually on corner exit."
        )
    elif mid_frac < 0.30:
        lines.append(
            "Throttle is a bit binary. There is some modulation, but you could "
            "smooth out your pickups to improve traction and consistency."
        )
    else:
        lines.append(
            "Throttle modulation looks good, with plenty of partial-throttle usage."
        )

    spikes = metrics["brake_spike_count"]
    if spikes == 0:
        lines.append("Braking is very smooth with no major spikes.")
    elif spikes <= 5:
        lines.append(
            "Braking is mostly smooth with a few spikes — watch for the occasional stab at the pedal."
        )
    else:
        lines.append(
            "There are frequent brake spikes. Try to squeeze the pedal on and off "
            "instead of jabbing it, to keep the car more stable."
        )

    ratio = metrics["mid_corner_speed_ratio"]
    if ratio < 0.55:
        lines.append(
            "Speed drops a lot in mid-corner compared to your straight-line pace. "
            "You may be over-slowing the car; focus on carrying more speed through the apex."
        )
    elif ratio < 0.70:
        lines.append(
            "Mid-corner speed is reasonable but could be higher. With more confidence in "
            "braking and earlier throttle, you can likely roll more speed through the turns."
        )
    else:
        lines.append(
            "Mid-corner speed is strong relative to your straight-line speed, suggesting "
            "you are carrying good pace through the corners."
        )

    return "\n".join(lines)

# ============================================================
# Main menu / interaction
# ============================================================

def main():
    filepath = input("Enter path to your MoTeC .ld file: ").strip()

    try:
        ld_main, raw_data = load_ld_core(filepath)
    except Exception as e:
        print("Error while reading .ld file:", e)
        return

    show_session_info(ld_main)

    track_name = ld_main.head.venue

    laps, best_lap_num, optimal_time = compute_lap_summaries(raw_data)


    ref_data = None
    ref_laps = None
    ref_best = None
    ref_ld = None
    manual_turns = None  # list of {"turn", "start_m", "end_m"} for this run

    while True:
        print("\nChoose analysis mode:")
        print("  1) Whole stint")
        print("  2) Load reference telemetry (.ld)")
        print("  3) Compare your lap vs reference lap")
        print("  0) Exit")
        choice = input("> ").strip()

        if choice == "0":
            break

        elif choice == "1":
            # Show lap table for the whole stint
            if laps:
                print_lap_table(laps, best_lap_num, optimal_time)
            else:
                print("No laps found in data.")

            try:
                metrics = compute_metrics(raw_data)
            except ValueError as e:
                print("Error computing metrics:", e)
                continue

            print("\n=== Whole-Stint Metrics ===")
            print(f"Samples:              {metrics['sample_count']}")
            print(f"Average throttle (%): {metrics['avg_throttle']:.1f}")
            print(f"Average brake (%):    {metrics['avg_brake']:.1f}")
            print(f"Max speed:            {metrics['max_speed']:.1f}")
            print(f"Min speed:            {metrics['min_speed']:.1f}")
            print(f"Throttle variability: {metrics['throttle_variability']:.1f}")
            print(f"Throttle mid-range:   {metrics['throttle_mid_fraction'] * 100:.1f}% of samples in 20–80%")
            print(f"Brake spikes:         {metrics['brake_spike_count']}")
            print(f"Mid-corner speed ratio (mid/straight): {metrics['mid_corner_speed_ratio']:.2f}")

            print("\n=== Coaching Feedback (Whole Stint) ===")
            print(generate_feedback(metrics))

        elif choice == "2":
            ref_path = input("Enter path to reference .ld file: ").strip()
            if not ref_path:
                continue
            try:
                ref_ld, ref_data = load_ld_core(ref_path)
                show_session_info(ref_ld)
                ref_laps, ref_best, ref_optimal_time = compute_lap_summaries(ref_data)
                print_lap_table(ref_laps, ref_best, ref_optimal_time)
            except Exception as e:
                print("Error loading reference file:", e)
                ref_data = None
                ref_laps = None
                ref_ld = None

        elif choice == "3":
            if ref_data is None or ref_laps is None:
                print("No reference telemetry loaded. Choose option 3 first.")
                continue
            if not laps:
                print("No laps in your main file.")
                continue

            print("\nYour laps:")
            print_lap_table(laps, best_lap_num, optimal_time)
            my_choice_str = input("\nChoose your lap number (blank = best): ").strip()
            if my_choice_str:
                try:
                    my_lap_num = int(my_choice_str)
                except ValueError:
                    print("Invalid lap number.")
                    continue
            else:
                my_lap_num = best_lap_num

            my_lap = next((l for l in laps if l["lap_num"] == my_lap_num), None)
            if my_lap is None:
                print("Chosen lap not found.")
                continue

            print("\nReference laps:")
            print_lap_table(ref_laps, ref_best, ref_optimal_time)
            ref_choice_str = input("\nChoose reference lap number (blank = best): ").strip()
            if ref_choice_str:
                try:
                    ref_lap_num = int(ref_choice_str)
                except ValueError:
                    print("Invalid lap number.")
                    continue
            else:
                ref_lap_num = ref_best

            ref_lap = next((l for l in ref_laps if l["lap_num"] == ref_lap_num), None)
            if ref_lap is None:
                print("Reference lap not found.")
                continue

            # Build profiles and compare
            my_prof = build_profile_for_lap(raw_data, my_lap["start_idx"], my_lap["end_idx"])
            ref_prof = build_profile_for_lap(ref_data, ref_lap["start_idx"], ref_lap["end_idx"])
            d_grid, delta_t, profs = resample_profiles(my_prof, ref_prof)
            t_me, s_me, th_me, br_me, lat_me = profs["me"]
            t_ref, s_ref, th_ref, br_ref, lat_ref = profs["ref"]

            total_delta = t_me[-1] - t_ref[-1]

            # Try to load segmentation for this track once
            if manual_turns is None:
                loaded = load_track_segments_for(track_name)

                if loaded is not None:
                    print(f"\nFound saved corner segmentation for track '{track_name}'.")
                    ans = input(
                        "Use existing segmentation (u) or overwrite with new values (o)? [u/o]: "
                    ).strip().lower()

                    if ans.startswith("o"):
                        # Overwrite: prompt again and save
                        manual_turns = prompt_corner_segments(my_prof["lap_length_m"])
                        save_track_segments_for(track_name, manual_turns)
                        print(f"Updated segmentation saved for track '{track_name}' to {SEGMENT_FILE}.")
                    else:
                        # Default: keep existing
                        manual_turns = loaded
                        print("Using saved segmentation.")
                else:
                    # No saved data: prompt user and save
                    manual_turns = prompt_corner_segments(my_prof["lap_length_m"])
                    save_track_segments_for(track_name, manual_turns)
                    print(f"Segmentation saved for track '{track_name}' to {SEGMENT_FILE}.")

            # Compute segment deltas using the (now known) segmentation
            segs = segment_deltas_manual(
                d_grid, delta_t, t_me, t_ref,
                my_prof["lap_length_m"],
                manual_turns,
            )

            # Enrich with avg speed/throttle/brake
            segs = enrich_segments_with_stats(
                segs,
                s_me, s_ref,
                th_me, th_ref,
                br_me, br_ref,
            )

            loss_seg = max(segs, key=lambda s: s["delta"])
            gain_seg = min(segs, key=lambda s: s["delta"])


            print(f"\n=== Lap Comparison: You vs Reference ===")
            print(f"Your lap {my_lap_num}:       {format_laptime(my_lap['lap_time'])}")
            print(f"Reference lap {ref_lap_num}: {format_laptime(ref_lap['lap_time'])}")
            print(f"Total delta (you - ref): {total_delta:+.3f} s")

            print("\nSegment breakdown (manual segmentation):")
            print("  Segment        Δtime (s)")
            print(" ---------------------------")
            for seg in segs:
                print(f"  {seg['name']:<12} {seg['delta']:+.3f}")

            # Biggest loss/gain FROM SEGMENTS
            print("\nBiggest time loss point:")
            print(f"     At {loss_seg['name']} you lose {loss_seg['delta']:+.3f} s.")
            print(f"     Speed:    you {loss_seg['speed_me']:.1f}, ref {loss_seg['speed_ref']:.1f}")
            print(f"     Throttle: you {loss_seg['thr_me']:.1f}%, ref {loss_seg['thr_ref']:.1f}%")
            print(f"     Brake:    you {loss_seg['br_me']:.1f}%, ref {loss_seg['br_ref']:.1f}%")

            print("\nBiggest time gain point:")
            print(f"     At {gain_seg['name']} you gain {gain_seg['delta']:+.3f} s.")
            print(f"     Speed:    you {gain_seg['speed_me']:.1f}, ref {gain_seg['speed_ref']:.1f}")
            print(f"     Throttle: you {gain_seg['thr_me']:.1f}%, ref {gain_seg['thr_ref']:.1f}%")
            print(f"     Brake:    you {gain_seg['br_me']:.1f}%, ref {gain_seg['br_ref']:.1f}%")

            # Optional full segment-by-segment detail
            ans = input("\nShow detailed segment-by-segment comparison? (y/n): ").strip().lower()
            if ans.startswith("y"):
                print_segment_details(segs)

        else:
            print("Invalid choice. Please enter 0, 1, 3, or 4.")

if __name__ == "__main__":
    main()