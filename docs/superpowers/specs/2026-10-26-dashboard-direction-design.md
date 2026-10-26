# Dashboard Direction Design

The dashboard will use a desktop two-column workstation layout. The left column is the live capture and operational telemetry surface: recording control, virtual LED ring, sound-direction compass, current request, pipeline trace, and ASR performance counters. The right column is reserved for the transcript so text remains readable during a meeting.

Each completed raw WAV clip will receive a direction estimate derived from the relative RMS energy of ReSpeaker microphone channels 1–6. This is an approximate fallback because the installed ALSA voice-card driver does not expose the XMOS firmware direction-of-arrival value. The API will include degree, compass label, confidence, and source (`energy_estimate`). A confidence below 0.10 is reported as uncertain rather than presented as a reliable speaker direction.

Direction metadata is attached to the capture-complete event and to the associated transcript line. The browser shows the newest direction in a 360-degree compass, and each transcript line shows its direction and confidence. Existing capture, queue, model, and error telemetry remain visible.

Tests cover the pure audio-direction estimator with a channel-dominant fixture and an even-energy uncertainty fixture. Manual browser verification covers column layout and API rendering.
