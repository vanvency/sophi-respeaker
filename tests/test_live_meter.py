import unittest
from array import array

from app import arecord_command, live_audio_snapshot, pulse_capture_sources


class LiveAudioSnapshotTests(unittest.TestCase):
    def test_reports_six_normalized_levels_and_direction(self):
        frames = array("i")
        for _ in range(40):
            frames.extend([10_000_000, 20_000_000, 400_000_000, 30_000_000,
                           10_000_000, 20_000_000, 0, 0])

        snapshot = live_audio_snapshot(frames.tobytes())

        self.assertEqual(len(snapshot["levels"]), 6)
        self.assertEqual(snapshot["levels"][2], 1.0)
        self.assertEqual(snapshot["direction"]["degree"], 120)
        self.assertFalse(snapshot["direction"]["uncertain"])

    def test_silence_is_uncertain(self):
        snapshot = live_audio_snapshot(bytes(8 * 4 * 20))

        self.assertEqual(snapshot["levels"], [0.0] * 6)
        self.assertTrue(snapshot["direction"]["uncertain"])

    def test_quiet_biased_noise_is_uncertain(self):
        """Static channel imbalance below the speech floor must not point the ring."""
        frames = array("i")
        for _ in range(40):
            frames.extend([2_400_000, 2_200_000, 2_000_000, 1_800_000, 8_000, 8_000, 0, 0])

        snapshot = live_audio_snapshot(frames.tobytes())

        self.assertTrue(snapshot["direction"]["uncertain"])
        self.assertEqual(snapshot["direction"]["reason"], "silence")

    def test_finds_the_respeaker_pulse_source(self):
        sources = "0\talsa_output.platform-bcm2835_audio.analog-stereo.monitor\n2\talsa_input.platform-soc_sound.multichannel-input\n"

        self.assertEqual(pulse_capture_sources(sources), ["2"])

    def test_capture_command_requests_low_latency_alsa_period(self):
        command = arecord_command()

        self.assertIn("--period-time=50000", command)
        self.assertIn("--buffer-time=250000", command)
        self.assertEqual(command[-1], "raw")


if __name__ == "__main__":
    unittest.main()
