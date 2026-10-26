"""ReSpeaker 6-mic array button and APA102 LED-ring controller."""
import atexit
import colorsys
import threading
import time

import RPi.GPIO as GPIO
import spidev

BUTTON_PIN = 26
LED_POWER_PIN = 5
LED_COUNT = 12

class ReSpeakerIO:
    def __init__(self, on_button):
        self.on_button = on_button
        self.lock = threading.Lock()
        self.status_frame = ((0, 0, 0), 1)
        self.direction_until = 0.0
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(LED_POWER_PIN, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(BUTTON_PIN, GPIO.FALLING, callback=self._pressed, bouncetime=250)
        self.spi = spidev.SpiDev()
        # The ReSpeaker APA102 ring is wired to SPI0 CE1, not CE0.
        self.spi.open(0, 1)
        self.spi.max_speed_hz = 8_000_000
        self.off()
        atexit.register(self.close)

    def _pressed(self, _pin):
        threading.Thread(target=self.on_button, daemon=True).start()

    def _pixels_locked(self, colors, brightness=8):
        frame = [0, 0, 0, 0]
        prefix = 0b11100000 | max(1, min(31, brightness))
        for red, green, blue in colors:
            frame.extend([prefix, blue, green, red])
        frame.extend([255, 255, 255, 255])
        self.spi.xfer2(frame)

    def pixels(self, colors, brightness=8):
        with self.lock:
            self._pixels_locked(colors, brightness)

    def _set_status(self, color, brightness, force=False):
        with self.lock:
            self.status_frame = (color, brightness)
            if force or time.monotonic() >= self.direction_until:
                self._pixels_locked([color] * LED_COUNT, brightness)

    def _restore_status(self):
        with self.lock:
            if time.monotonic() >= self.direction_until:
                color, brightness = self.status_frame
                self._pixels_locked([color] * LED_COUNT, brightness)

    def off(self): self._set_status((0, 0, 0), 1, force=True)
    def standby(self): self._set_status((0, 32, 8), 5, force=True)
    def recording(self): self._set_status((96, 0, 0), 10)
    def transcribing(self): self._set_status((90, 40, 0), 8)
    def error(self): self._set_status((96, 0, 40), 10, force=True)
    def direction(self, degree, hold_seconds=2):
        center = round((degree % 360) / 30) % LED_COUNT
        colors = []
        for index in range(LED_COUNT):
            distance = min((index-center) % LED_COUNT, (center-index) % LED_COUNT)
            colors.append((0, max(0, 80 - distance * 35), max(0, 110 - distance * 50)))
        with self.lock:
            self.direction_until = time.monotonic() + hold_seconds
            self._pixels_locked(colors, 8)
        timer = threading.Timer(hold_seconds, self._restore_status)
        timer.daemon = True
        timer.start()

    def close(self):
        try: self.off(); self.spi.close(); GPIO.cleanup()
        except Exception: pass
