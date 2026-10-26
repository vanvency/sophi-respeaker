import unittest

from app import estimate_direction


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


if __name__ == "__main__":
    unittest.main()
