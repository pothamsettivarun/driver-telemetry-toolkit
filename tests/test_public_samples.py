import contextlib
import io
import unittest
from pathlib import Path

from main import compute_lap_summaries, load_ld_core


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PublicSampleTests(unittest.TestCase):
    def _load(self, filename):
        with contextlib.redirect_stdout(io.StringIO()):
            log, data = load_ld_core(str(PROJECT_ROOT / "examples/data" / filename))
        laps, best_lap, _ = compute_lap_summaries(data)
        return log, laps, best_lap

    def test_samples_are_anonymized_single_fastest_laps(self):
        cases = [
            ("author_fastest_lap.ld", "Author Driver", 94.4914048),
            ("reference_fastest_lap.ld", "Reference Driver", 94.6871040),
        ]

        for filename, driver_role, expected_time in cases:
            with self.subTest(filename=filename):
                log, laps, best_lap = self._load(filename)
                completed = [lap for lap in laps if not lap["is_incomplete"]]

                self.assertEqual(log.head.driver, driver_role)
                self.assertEqual(len(list(log)), 11)
                self.assertEqual(best_lap, 1)
                self.assertEqual(len(completed), 1)
                self.assertAlmostEqual(completed[0]["lap_time"], expected_time, places=3)

    def test_published_finish_line_delta_matches_case_study(self):
        _, author_laps, _ = self._load("author_fastest_lap.ld")
        _, reference_laps, _ = self._load("reference_fastest_lap.ld")
        delta = author_laps[0]["lap_time"] - reference_laps[0]["lap_time"]

        self.assertAlmostEqual(delta, -0.1957, places=3)


if __name__ == "__main__":
    unittest.main()

