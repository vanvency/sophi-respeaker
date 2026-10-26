import unittest

import app


class CaptureStopTests(unittest.TestCase):
    def test_stop_terminates_the_active_arecord_process(self):
        class FakeProcess:
            def __init__(self):
                self.terminated = False

            def poll(self):
                return None

            def terminate(self):
                self.terminated = True

        class FakeIO:
            def standby(self):
                pass

        process = FakeProcess()
        prior_process, prior_io = getattr(app, "capture_process", None), app.io
        try:
            app.capture_process = process
            app.io = FakeIO()
            app.state["running"] = True
            app.stop_listening()
        finally:
            app.capture_process, app.io = prior_process, prior_io

        self.assertTrue(process.terminated)


if __name__ == "__main__":
    unittest.main()
