import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calibration import fit_step


class LongCalibrationTest(unittest.TestCase):
    def rows(self):
        # A continuous, settled air step; reducing its 18,000 samples gives 1.2 s
        # between fitting points, which is not an acquisition interruption.
        return [
            {"t": 1000 + i * 0.1, "raw": 25 + 45 * math.exp(-i * 0.1 / 60)}
            for i in range(18000)
        ]

    def test_long_continuous_step_is_not_reported_as_a_gap(self):
        result = fit_step(self.rows())
        self.assertTrue(result["valid"], result)
        self.assertLess(abs(result["tau_s"] - 60), 1)

    def test_real_gap_survives_fitting_downsampling(self):
        rows = self.rows()
        rows = [r for r in rows if not 1500 <= r["t"] < 1502]
        self.assertEqual(
            fit_step(rows),
            {"valid": False, "reason": "Data gap: repeat the calibration"},
        )


if __name__ == "__main__":
    unittest.main()
