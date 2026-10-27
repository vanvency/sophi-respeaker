import unittest

from respeaker_io import direction_colors


class LedDirectionTests(unittest.TestCase):
    def test_uncertain_direction_uses_all_dim_red_leds(self):
        colors = direction_colors(0, uncertain=True)

        self.assertEqual(len(colors), 12)
        self.assertTrue(all(color == (20, 0, 0) for color in colors))

    def test_certain_direction_uses_exactly_two_bright_red_leds(self):
        colors = direction_colors(90, uncertain=False)

        self.assertEqual(sum(color == (150, 0, 0) for color in colors), 2)
        self.assertEqual(sum(color == (0, 0, 0) for color in colors), 10)


if __name__ == "__main__":
    unittest.main()
