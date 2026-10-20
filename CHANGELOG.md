## v0.2.0

- Coffee/general recording modes; general sessions never auto-end on cooling.
- Conservative automatic DROP candidates with 20 s confirmation, retrospective marks and undo for the latest auto-ended recording.
- Live FC START development time/ratio, frozen at DROP/STOP.
- Optional persisted green/roasted weights and weight-loss calculation for completed coffee records.
- Zero-based 16-minute recording view that expands to keep the complete session.
- Backward-compatible database migration; historical events are not reinterpreted.

# Changelog

## 0.1.0

- Local-first, shared 10 Hz target temperature collection with persistent SQLite history.
- Device discovery, manual IP testing/selection and saved local configuration.
- Live/held scope view, zero-based vertical zoom and fixed 0–250°C scale.
- D1/D2 seconds/minutes display, recording events, archive and CSV exports.
- Conditional five-minute thermal-balance forecasts with frozen later scoring.
- Optional manual probe step-response tests.
- Docker/Compose setup, source-only release audit and CI checks.

Firmware, Wi-Fi credentials and runtime measurement data are excluded.
