import unittest

from main import compute_lap_summaries


class ComputeLapSummariesTests(unittest.TestCase):
    def test_empty_input_always_returns_three_values(self):
        self.assertEqual(compute_lap_summaries({"time": [], "lap": []}), ([], None, None))

    def test_single_complete_lap_is_valid_when_distance_covers_track(self):
        data = {
            "time": [0.0, 1.0, 2.0],
            "lap": [1.0, 1.0, 1.0],
            "lap_dist_pct": [0.0, 50.0, 100.0],
            "lap_best_lap": [1.0, 1.0, 1.0],
            "lap_best_time": [2.0, 2.0, 2.0],
        }

        laps, best_lap, _ = compute_lap_summaries(data)

        self.assertEqual(best_lap, 1)
        self.assertFalse(laps[0]["is_incomplete"])
        self.assertAlmostEqual(laps[0]["lap_time"], 2.0)

    def test_partial_edge_laps_are_excluded(self):
        data = {
            "time": list(map(float, range(9))),
            "lap": [0, 0, 1, 1, 1, 2, 2, 2, 2],
            "lap_dist_pct": [60, 90, 0, 50, 100, 0, 20, 40, 60],
        }

        laps, best_lap, _ = compute_lap_summaries(data)

        self.assertEqual(best_lap, 1)
        self.assertEqual(
            [lap["lap_num"] for lap in laps if lap["is_incomplete"]],
            [0, 2],
        )

    def test_reported_best_metadata_controls_selection_and_time(self):
        data = {
            "time": list(map(float, range(11))),
            "lap": [0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3],
            "lap_dist_pct": [50, 90, 0, 50, 100, 0, 50, 100, 0, 20, 40],
            "lap_last_time": [0, 0, 0, 0, 0, 0, 0, 4.2, 4.2, 3.5, 3.5],
            "lap_best_lap": [1] * 11,
            "lap_best_time": [4.2] * 11,
        }

        laps, best_lap, _ = compute_lap_summaries(data)
        completed = {lap["lap_num"]: lap for lap in laps if not lap["is_incomplete"]}

        self.assertEqual(best_lap, 1)
        self.assertAlmostEqual(completed[1]["lap_time"], 4.2)
        self.assertAlmostEqual(completed[2]["lap_time"], 3.5)

    def test_rejects_mismatched_time_and_lap_channels(self):
        with self.assertRaisesRegex(ValueError, "different sample counts"):
            compute_lap_summaries({"time": [0.0, 1.0], "lap": [1.0]})


if __name__ == "__main__":
    unittest.main()
