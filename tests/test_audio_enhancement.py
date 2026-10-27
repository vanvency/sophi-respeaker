import unittest

from app import asr_audio_filter


class AudioEnhancementTests(unittest.TestCase):
    def test_filter_keeps_speech_band_and_enables_adaptive_denoise(self):
        filters = asr_audio_filter()

        self.assertIn("pan=mono", filters)
        self.assertIn("highpass=f=90", filters)
        self.assertIn("lowpass=f=7600", filters)
        self.assertIn("afftdn=nr=18:nf=-45:tn=1:tr=1", filters)
        self.assertIn("dynaudnorm", filters)


if __name__ == "__main__":
    unittest.main()
