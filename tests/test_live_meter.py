import unittest
from array import array

from app import live_audio_snapshot


class LiveAudioSnapshotTests(unittest.TestCase):
    def test_reports_six_normalized_levels_and_direction(self):
        frames = array("i")
        for _ in range(40):
            frames.extend([10, 20, 400, 30, 10, 20, 0, 0])

        snapshot = live_audio_snapshot(frames.tobytes())

        self.assertEqual(len(snapshot["levels"]), 6)
        self.assertEqual(snapshot["levels"][2], 1.0)
        self.assertEqual(snapshot["direction"]["degree"], 120)
        self.assertFalse(snapshot["direction"]["uncertain"])

    def test_silence_is_uncertain(self):
        snapshot = live_audio_snapshot(bytes(8 * 4 * 20))

        self.assertEqual(snapshot["levels"], [0.0] * 6)
        self.assertTrue(snapshot["direction"]["uncertain"])


if __name__ == "__main__":
    unittest.main()
