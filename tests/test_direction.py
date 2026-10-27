import unittest

import app
from app import LIVE_WINDOW_SECONDS, estimate_direction, show_direction


class DirectionEstimateTests(unittest.TestCase):
    def test_dominant_microphone_maps_to_its_sector(self):
        result = estimate_direction([1, 1, 1, 1, 100, 1])

        self.assertEqual(result["degree"], 240)
        self.assertEqual(result["label"], "SW")
        self.assertGreater(result["confidence"], 0.9)
        self.assertFalse(result["uncertain"])

    def test_even_energy_is_marked_uncertain(self):
        result = estimate_direction([10, 10, 10, 10, 10, 10])

        self.assertTrue(result["uncertain"])
        self.assertEqual(result["confidence"], 0.0)

    def test_high_confidence_direction_is_sent_to_led_ring(self):
        calls = []

        class FakeIO:
            def direction(self, degree, uncertain):
                calls.append((degree, uncertain))

        previous_io = app.io
        app.io = FakeIO()
        try:
            show_direction({"available": True, "uncertain": False, "degree": 180})
        finally:
            app.io = previous_io

        self.assertEqual(calls, [(180, False)])

    def test_uncertain_direction_is_sent_to_led_ring_as_dim_red(self):
        calls = []

        class FakeIO:
            def direction(self, degree, uncertain):
                calls.append((degree, uncertain))

        previous_io = app.io
        app.io = FakeIO()
        try:
            show_direction({"available": True, "uncertain": True, "degree": 180})
        finally:
            app.io = previous_io

        self.assertEqual(calls, [(180, True)])

    def test_live_analysis_window_is_100_milliseconds(self):
        self.assertEqual(LIVE_WINDOW_SECONDS, 0.10)


if __name__ == "__main__":
    unittest.main()
