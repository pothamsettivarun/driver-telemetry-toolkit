import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np

# Import your existing core functions from main.py
from main import (
    load_ld_core,
    show_session_info,
    compute_lap_summaries,
    compute_metrics,
    generate_feedback,
    format_laptime,
    build_profile_for_lap,
    resample_profiles,
    segment_deltas_manual,
    enrich_segments_with_stats,
    load_track_segments_for,
    save_track_segments_for,
)

# -----------------------------
# Small UI helpers
# -----------------------------

def laps_to_display_list(laps, best_lap_num):
    """
    Build a list of display strings for a Combobox.
    Includes a "Best" option + all completed laps.
    """
    items = []
    if best_lap_num is not None:
        items.append(f"Best (Lap {best_lap_num})")
    for lap in laps:
        if lap.get("is_incomplete"):
            continue
        items.append(f"Lap {lap['lap_num']} — {format_laptime(lap['lap_time'])}")
    return items

def parse_lap_choice(choice: str, best_lap_num: int):
    """
    Parse combobox choice -> lap_num integer.
    """
    if choice.startswith("Best"):
        return best_lap_num
    # "Lap 24 — 1:36.383"
    parts = choice.split()
    if len(parts) >= 2 and parts[0] == "Lap":
        return int(parts[1])
    raise ValueError("Could not parse lap selection.")


class SegmentEditor(tk.Toplevel):
    """
    Simple segmentation editor:
    user pastes lines like:
      342-558
      684-718
      891-1035
    each line = Turn 1, Turn 2, ...
    blank lines ignored.
    """
    def __init__(self, parent, lap_length_m: float, existing=None):
        super().__init__(parent)
        self.title("Corner Segmentation Editor")
        self.geometry("520x420")
        self.resizable(True, True)

        self.lap_length_m = float(lap_length_m)
        self.result = None  # list of dicts or None if cancelled

        lbl = tk.Label(
            self,
            text=(
                f"Enter corner segments in meters (0 to {self.lap_length_m:.1f}).\n"
                "One line per turn, format: start-end\n"
                "Example:\n"
                "  342-558\n"
                "  684-718\n"
                "Blank lines are ignored."
            ),
            justify="left",
        )
        lbl.pack(anchor="w", padx=10, pady=10)

        self.text = tk.Text(self, height=14, wrap="none")
        self.text.pack(fill="both", expand=True, padx=10, pady=5)

        # preload existing
        if existing:
            lines = [f"{s['start_m']:.0f}-{s['end_m']:.0f}" for s in existing]
            self.text.insert("1.0", "\n".join(lines) + "\n")

        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10, pady=10)

        tk.Button(btns, text="Cancel", command=self._cancel).pack(side="right", padx=5)
        tk.Button(btns, text="Save", command=self._save).pack(side="right", padx=5)

        self.transient(parent)
        self.grab_set()
        self.text.focus_set()

    def _cancel(self):
        self.result = None
        self.destroy()

    def _save(self):
        raw = self.text.get("1.0", "end").strip()
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

        turns = []
        idx = 1
        for ln in lines:
            ln = ln.replace("–", "-").replace("—", "-")
            parts = ln.split("-")
            if len(parts) != 2:
                messagebox.showerror("Invalid input", f"Bad line: '{ln}'\nUse start-end.")
                return
            try:
                start_m = float(parts[0])
                end_m = float(parts[1])
            except ValueError:
                messagebox.showerror("Invalid input", f"Bad numbers in: '{ln}'")
                return

            if not (0.0 <= start_m < end_m <= self.lap_length_m):
                messagebox.showerror(
                    "Invalid range",
                    f"Line '{ln}' must satisfy 0 <= start < end <= {self.lap_length_m:.1f}"
                )
                return

            turns.append({"turn": idx, "start_m": start_m, "end_m": end_m})
            idx += 1

        if not turns:
            messagebox.showerror("No turns", "Please enter at least one turn segment.")
            return

        # Optional: warn if overlaps / unsorted
        turns_sorted = sorted(turns, key=lambda t: t["start_m"])
        for i in range(1, len(turns_sorted)):
            if turns_sorted[i]["start_m"] < turns_sorted[i-1]["end_m"]:
                messagebox.showerror("Overlap", "Turns overlap. Please fix the ranges.")
                return

        self.result = turns_sorted
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Driver Telemetry Toolkit")
        self.geometry("1100x760")

        # Main state
        self.main_path = None
        self.ld_main = None
        self.raw_data = None
        self.track_name = None
        self.laps = None
        self.best_lap_num = None
        self.optimal_time = None

        # Reference state
        self.ref_path = None
        self.ref_ld = None
        self.ref_data = None
        self.ref_laps = None
        self.ref_best = None
        self.ref_optimal_time = None

        # Segmentation
        self.manual_turns = None  # loaded/saved per track

        # ---- Layout ----
        header = tk.Frame(self)
        header.pack(fill="x", padx=10, pady=10)

        tk.Button(header, text="Load Your .ld…", command=self.load_main_file).pack(side="left")
        self.main_label = tk.Label(header, text="(no main file loaded)", anchor="w")
        self.main_label.pack(side="left", padx=10, fill="x", expand=True)

        tk.Button(header, text="Load Reference .ld…", command=self.load_ref_file).pack(side="left", padx=(10, 0))
        self.ref_label = tk.Label(header, text="(no reference loaded)", anchor="w")
        self.ref_label.pack(side="left", padx=10, fill="x", expand=True)

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_main = tk.Frame(self.tabs)
        self.tab_ref = tk.Frame(self.tabs)
        self.tab_cmp = tk.Frame(self.tabs)

        self.tabs.add(self.tab_main, text="Main Stint")
        self.tabs.add(self.tab_ref, text="Reference Stint")
        self.tabs.add(self.tab_cmp, text="Compare")

        # ---- Main tab ----
        self.main_info = tk.Text(self.tab_main, height=6, wrap="word")
        self.main_info.pack(fill="x", padx=8, pady=(8, 4))

        self.main_table = self._make_lap_table(self.tab_main)
        self.main_table.pack(fill="both", expand=True, padx=8, pady=4)

        tk.Button(self.tab_main, text="Run Full Stint Metrics", command=self.run_main_metrics).pack(padx=8, pady=(4, 8), anchor="w")

        self.main_metrics = tk.Text(self.tab_main, height=10, wrap="word")
        self.main_metrics.pack(fill="x", padx=8, pady=(0, 8))

        # ---- Reference tab ----
        self.ref_info = tk.Text(self.tab_ref, height=6, wrap="word")
        self.ref_info.pack(fill="x", padx=8, pady=(8, 4))

        self.ref_table = self._make_lap_table(self.tab_ref)
        self.ref_table.pack(fill="both", expand=True, padx=8, pady=4)

        tk.Button(self.tab_ref, text="Run Full Stint Metrics (Reference)", command=self.run_ref_metrics).pack(padx=8, pady=(4, 8), anchor="w")

        self.ref_metrics = tk.Text(self.tab_ref, height=10, wrap="word")
        self.ref_metrics.pack(fill="x", padx=8, pady=(0, 8))

        # ---- Compare tab ----
        top_cmp = tk.Frame(self.tab_cmp)
        top_cmp.pack(fill="x", padx=8, pady=8)

        tk.Label(top_cmp, text="Your lap:").pack(side="left")
        self.cmb_my = ttk.Combobox(top_cmp, width=38, state="readonly")
        self.cmb_my.pack(side="left", padx=8)

        tk.Label(top_cmp, text="Reference lap:").pack(side="left", padx=(20, 0))
        self.cmb_ref = ttk.Combobox(top_cmp, width=38, state="readonly")
        self.cmb_ref.pack(side="left", padx=8)

        tk.Button(top_cmp, text="Compare", command=self.run_compare).pack(side="left", padx=(20, 0))

        seg_bar = tk.Frame(self.tab_cmp)
        seg_bar.pack(fill="x", padx=8, pady=(0, 8))

        self.seg_status = tk.Label(seg_bar, text="Segments: (not loaded)")
        self.seg_status.pack(side="left")

        tk.Button(seg_bar, text="Edit / Overwrite Segments…", command=self.edit_segments).pack(side="left", padx=10)
        tk.Button(seg_bar, text="Reload Saved Segments", command=self.reload_segments).pack(side="left")

        self.cmp_out = tk.Text(self.tab_cmp, wrap="word")
        self.cmp_out.pack(fill="both", expand=True, padx=8, pady=8)

    def _make_lap_table(self, parent):
        cols = ("lap", "time", "d_best", "d_opt")
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=12)
        tree.heading("lap", text="Lap")
        tree.heading("time", text="Time")
        tree.heading("d_best", text="ΔBest")
        tree.heading("d_opt", text="ΔOpt")
        tree.column("lap", width=80, anchor="center")
        tree.column("time", width=120, anchor="center")
        tree.column("d_best", width=120, anchor="center")
        tree.column("d_opt", width=120, anchor="center")
        return tree

    def _clear_tree(self, tree):
        for item in tree.get_children():
            tree.delete(item)

    def _append_info_text(self, widget: tk.Text, txt: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", txt)
        widget.configure(state="disabled")

    def _append_out(self, widget: tk.Text, txt: str):
        widget.configure(state="normal")
        widget.insert("end", txt)
        widget.see("end")
        widget.configure(state="disabled")

    def load_main_file(self):
        path = filedialog.askopenfilename(
            title="Select your MoTeC .ld file",
            filetypes=[("MoTeC Log", "*.ld"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            ld_main, raw_data = load_ld_core(path)
            laps, best_lap_num, optimal_time = compute_lap_summaries(raw_data)

            self.main_path = path
            self.ld_main = ld_main
            self.raw_data = raw_data
            self.laps = laps
            self.best_lap_num = best_lap_num
            self.optimal_time = optimal_time
            self.track_name = ld_main.head.venue

            self.main_label.config(text=path)
            self.manual_turns = None
            self.seg_status.config(text="Segments: (not loaded)")

            # Session info (reuse your console printer by capturing its output lightly)
            info = self._session_info_string(ld_main)
            self._append_info_text(self.main_info, info)

            # Lap table
            self.populate_lap_table(self.main_table, self.laps, self.best_lap_num)

            # Update compare dropdown
            self.refresh_compare_dropdowns()

            # Jump to main tab
            self.tabs.select(self.tab_main)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load main file:\n{e}")

    def load_ref_file(self):
        path = filedialog.askopenfilename(
            title="Select reference MoTeC .ld file",
            filetypes=[("MoTeC Log", "*.ld"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            ref_ld, ref_data = load_ld_core(path)
            ref_laps, ref_best, ref_opt = compute_lap_summaries(ref_data)

            self.ref_path = path
            self.ref_ld = ref_ld
            self.ref_data = ref_data
            self.ref_laps = ref_laps
            self.ref_best = ref_best
            self.ref_optimal_time = ref_opt

            self.ref_label.config(text=path)

            info = self._session_info_string(ref_ld)
            self._append_info_text(self.ref_info, info)

            self.populate_lap_table(self.ref_table, self.ref_laps, self.ref_best)

            self.refresh_compare_dropdowns()

            self.tabs.select(self.tab_ref)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load reference file:\n{e}")

    def _session_info_string(self, ldd):
        # build a compact session info string without relying on print capture
        driver = ldd.head.driver
        car = ldd.head.vehicleid
        track = ldd.head.venue
        lines = [
            "=== Session Info ===",
            f"Driver: {driver}",
            f"Car:    {car}",
            f"Track:  {track}",
        ]
        # conditions are already handled in your show_session_info, but here we keep it minimal
        return "\n".join(lines)

    def populate_lap_table(self, tree, laps, best_lap_num):
        self._clear_tree(tree)

        # Show OPT as a special first row (if available)
        # We don’t store optimal_time inside laps; we’ll infer from best lap row's delta_opt_fixed if present.
        # Better: use the object's optimal time if this is main table/ref table.
        if tree is self.main_table:
            opt = self.optimal_time
        else:
            opt = self.ref_optimal_time

        if opt is not None:
            tree.insert("", "end", values=("OPT", format_laptime(opt), "N/A", "+0.000"))

        for lap in laps:
            lap_num = lap["lap_num"]
            t = format_laptime(lap["lap_time"])

            d_best = lap.get("delta_to_best", None)
            if d_best is None:
                d_best_str = "N/A"
            else:
                d_best_str = f"{d_best:+.3f}" if abs(d_best) > 1e-4 else "+0.000"

            d_opt = lap.get("delta_opt_fixed", lap.get("delta_opt", None))
            d_opt_str = f"{d_opt:+.3f}" if d_opt is not None else "N/A"

            tag = ""
            if lap.get("is_incomplete"):
                tag = " (incomplete)"

            star = "*" if (lap_num == best_lap_num and not lap.get("is_incomplete")) else ""
            tree.insert("", "end", values=(f"{star}{lap_num}{tag}", t, d_best_str, d_opt_str))

    def refresh_compare_dropdowns(self):
        # Only populate if data exists
        if self.laps and self.best_lap_num is not None:
            self.cmb_my["values"] = laps_to_display_list(self.laps, self.best_lap_num)
            self.cmb_my.set(f"Best (Lap {self.best_lap_num})")
        else:
            self.cmb_my["values"] = []
            self.cmb_my.set("")

        if self.ref_laps and self.ref_best is not None:
            self.cmb_ref["values"] = laps_to_display_list(self.ref_laps, self.ref_best)
            self.cmb_ref.set(f"Best (Lap {self.ref_best})")
        else:
            self.cmb_ref["values"] = []
            self.cmb_ref.set("")

    def run_main_metrics(self):
        if self.raw_data is None:
            messagebox.showinfo("Main file", "Load your .ld file first.")
            return
        try:
            m = compute_metrics(self.raw_data)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to compute metrics:\n{e}")
            return

        txt = []
        txt.append("=== Whole-Stint Metrics ===")
        txt.append(f"Samples:              {m['sample_count']}")
        txt.append(f"Average throttle (%): {m['avg_throttle']:.1f}")
        txt.append(f"Average brake (%):    {m['avg_brake']:.1f}")
        txt.append(f"Max speed (km/h):     {m['max_speed'] * 3.6:.1f}")
        txt.append(f"Min speed (km/h):     {m['min_speed'] * 3.6:.1f}")
        txt.append(f"Throttle variability: {m['throttle_variability']:.1f}")
        txt.append(f"Throttle mid-range:   {m['throttle_mid_fraction'] * 100:.1f}% of samples in 20–80%")
        txt.append(f"Brake spikes:         {m['brake_spike_count']}")
        txt.append(f"Mid-corner speed ratio (mid/straight): {m['mid_corner_speed_ratio']:.2f}")
        txt.append("")
        txt.append("=== Coaching Feedback ===")
        txt.append(generate_feedback(m))

        self._append_info_text(self.main_metrics, "\n".join(txt))
        self.tabs.select(self.tab_main)

    def run_ref_metrics(self):
        if self.ref_data is None:
            messagebox.showinfo("Reference file", "Load a reference .ld file first.")
            return
        try:
            m = compute_metrics(self.ref_data)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to compute metrics:\n{e}")
            return

        txt = []
        txt.append("=== Reference Stint Metrics ===")
        txt.append(f"Samples:              {m['sample_count']}")
        txt.append(f"Average throttle (%): {m['avg_throttle']:.1f}")
        txt.append(f"Average brake (%):    {m['avg_brake']:.1f}")
        txt.append(f"Max speed (km/h):     {m['max_speed'] * 3.6:.1f}")
        txt.append(f"Min speed (km/h):     {m['min_speed'] * 3.6:.1f}")
        txt.append(f"Throttle variability: {m['throttle_variability']:.1f}")
        txt.append(f"Throttle mid-range:   {m['throttle_mid_fraction'] * 100:.1f}% of samples in 20–80%")
        txt.append(f"Brake spikes:         {m['brake_spike_count']}")
        txt.append(f"Mid-corner speed ratio (mid/straight): {m['mid_corner_speed_ratio']:.2f}")
        txt.append("")
        txt.append("=== Coaching Feedback ===")
        txt.append(generate_feedback(m))

        self._append_info_text(self.ref_metrics, "\n".join(txt))
        self.tabs.select(self.tab_ref)

    def reload_segments(self):
        if not self.track_name:
            messagebox.showinfo("Segments", "Load your main .ld file first.")
            return
        loaded = load_track_segments_for(self.track_name)
        if loaded is None:
            messagebox.showinfo("Segments", "No saved segments found for this track yet.")
            return
        self.manual_turns = loaded
        self.seg_status.config(text=f"Segments: loaded for '{self.track_name}' ({len(loaded)} turns)")

    def edit_segments(self):
        if self.raw_data is None or self.laps is None or self.best_lap_num is None:
            messagebox.showinfo("Segments", "Load your main .ld file first.")
            return

        # Use best lap to estimate lap length for validation
        best_lap = next((l for l in self.laps if l["lap_num"] == self.best_lap_num), None)
        if best_lap is None:
            messagebox.showerror("Segments", "Could not find best lap to derive lap length.")
            return

        prof = build_profile_for_lap(self.raw_data, best_lap["start_idx"], best_lap["end_idx"])
        lap_len = prof["lap_length_m"]

        existing = load_track_segments_for(self.track_name)
        dlg = SegmentEditor(self, lap_len, existing=existing)
        self.wait_window(dlg)

        if dlg.result is None:
            return  # cancelled

        save_track_segments_for(self.track_name, dlg.result)
        self.manual_turns = dlg.result
        self.seg_status.config(text=f"Segments: loaded for '{self.track_name}' ({len(dlg.result)} turns)")
        messagebox.showinfo("Segments", "Segmentation saved.")

    def ensure_segments(self, lap_length_m: float) -> bool:
        """
        Ensure manual_turns exists. If not, try load saved. If none, open editor.
        Returns True if we have segments, else False.
        """
        if self.manual_turns is not None:
            return True

        if not self.track_name:
            return False

        loaded = load_track_segments_for(self.track_name)
        if loaded is not None:
            self.manual_turns = loaded
            self.seg_status.config(text=f"Segments: loaded for '{self.track_name}' ({len(loaded)} turns)")
            return True

        # No saved segments: open editor
        dlg = SegmentEditor(self, lap_length_m, existing=None)
        self.wait_window(dlg)
        if dlg.result is None:
            return False

        save_track_segments_for(self.track_name, dlg.result)
        self.manual_turns = dlg.result
        self.seg_status.config(text=f"Segments: loaded for '{self.track_name}' ({len(dlg.result)} turns)")
        return True

    def run_compare(self):
        self.cmp_out.configure(state="normal")
        self.cmp_out.delete("1.0", "end")
        self.cmp_out.configure(state="disabled")

        if self.raw_data is None or self.laps is None:
            messagebox.showinfo("Compare", "Load your main .ld file first.")
            return
        if self.ref_data is None or self.ref_laps is None:
            messagebox.showinfo("Compare", "Load a reference .ld file first.")
            return

        try:
            my_lap_num = parse_lap_choice(self.cmb_my.get(), self.best_lap_num)
            ref_lap_num = parse_lap_choice(self.cmb_ref.get(), self.ref_best)
        except Exception:
            messagebox.showerror("Compare", "Please select both laps from the dropdowns.")
            return

        my_lap = next((l for l in self.laps if l["lap_num"] == my_lap_num), None)
        ref_lap = next((l for l in self.ref_laps if l["lap_num"] == ref_lap_num), None)
        if my_lap is None or ref_lap is None:
            messagebox.showerror("Compare", "Could not find one of the selected laps.")
            return

        my_prof = build_profile_for_lap(self.raw_data, my_lap["start_idx"], my_lap["end_idx"])
        ref_prof = build_profile_for_lap(self.ref_data, ref_lap["start_idx"], ref_lap["end_idx"])
        d_grid, delta_t, profs = resample_profiles(my_prof, ref_prof)
        t_me, s_me, th_me, br_me, lat_me = profs["me"]
        t_ref, s_ref, th_ref, br_ref, lat_ref = profs["ref"]

        # Ensure segments (GUI-based)
        if not self.ensure_segments(my_prof["lap_length_m"]):
            messagebox.showinfo("Compare", "Segmentation is required to compare laps. Cancelled.")
            return

        segs = segment_deltas_manual(d_grid, delta_t, t_me, t_ref, my_prof["lap_length_m"], self.manual_turns)
        segs = enrich_segments_with_stats(segs, s_me, s_ref, th_me, th_ref, br_me, br_ref)

        if not segs:
            messagebox.showerror("Compare", "No valid comparison segments were found.")
            return

        total_delta = my_lap["lap_time"] - ref_lap["lap_time"]
        loss_seg = max(segs, key=lambda s: s["delta"])
        gain_seg = min(segs, key=lambda s: s["delta"])

        out = []
        out.append("=== Lap Comparison: You vs Reference ===")
        out.append(f"Your lap {my_lap_num}:       {format_laptime(my_lap['lap_time'])}")
        out.append(f"Reference lap {ref_lap_num}: {format_laptime(ref_lap['lap_time'])}")
        out.append(f"Total delta (you - ref): {total_delta:+.3f} s")
        out.append("")
        out.append("Segment breakdown:")
        out.append("  Segment        Δtime (s)")
        out.append(" ---------------------------")
        for seg in segs:
            out.append(f"  {seg['name']:<12} {seg['delta']:+.3f}")

        out.append("")
        out.append("Biggest time loss point:")
        out.append(f"     At {loss_seg['name']} you lose {loss_seg['delta']:+.3f} s.")
        out.append(
            f"     Speed (km/h): you {loss_seg['speed_me'] * 3.6:.1f}, "
            f"ref {loss_seg['speed_ref'] * 3.6:.1f}"
        )
        out.append(f"     Throttle: you {loss_seg['thr_me']:.1f}%, ref {loss_seg['thr_ref']:.1f}%")
        out.append(f"     Brake:    you {loss_seg['br_me']:.1f}%, ref {loss_seg['br_ref']:.1f}%")

        out.append("")
        out.append("Biggest time gain point:")
        out.append(f"     At {gain_seg['name']} you gain {gain_seg['delta']:+.3f} s.")
        out.append(
            f"     Speed (km/h): you {gain_seg['speed_me'] * 3.6:.1f}, "
            f"ref {gain_seg['speed_ref'] * 3.6:.1f}"
        )
        out.append(f"     Throttle: you {gain_seg['thr_me']:.1f}%, ref {gain_seg['thr_ref']:.1f}%")
        out.append(f"     Brake:    you {gain_seg['br_me']:.1f}%, ref {gain_seg['br_ref']:.1f}%")

        out.append("")
        out.append("Detailed segment-by-segment:")
        for seg in segs:
            out.append(f"\n{seg['name']}")
            out.append(f"     Δtime (s): {seg['delta']:+.3f}")
            out.append(
                f"     Speed (km/h): you {seg['speed_me'] * 3.6:.1f}, "
                f"ref {seg['speed_ref'] * 3.6:.1f}"
            )
            out.append(f"     Throttle:  you {seg['thr_me']:.1f}%, ref {seg['thr_ref']:.1f}%")
            out.append(f"     Brake:     you {seg['br_me']:.1f}%, ref {seg['br_ref']:.1f}%")

        self._append_out(self.cmp_out, "\n".join(out) + "\n")
        self.tabs.select(self.tab_cmp)


if __name__ == "__main__":
    App().mainloop()
