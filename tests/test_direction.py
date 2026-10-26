import unittest

import app
from app import estimate_direction, show_direction


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
            def direction(self, degree):
                calls.append(degree)

        previous_io = app.io
        app.io = FakeIO()
        try:
            show_direction({"available": True, "uncertain": False, "degree": 180})
        finally:
            app.io = previous_io

        self.assertEqual(calls, [180])

    def test_uncertain_direction_is_not_sent_to_led_ring(self):
        calls = []

        class FakeIO:
            def direction(self, degree):
                calls.append(degree)

        previous_io = app.io
        app.io = FakeIO()
        try:
            show_direction({"available": True, "uncertain": True, "degree": 180})
        finally:
            app.io = previous_io

        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
