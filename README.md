# Thermal Scope

[English](README.md) | [简体中文](README.zh-CN.md)

A local-first PT100 temperature instrument for a home server, NAS or desktop. One collector reads a compatible ESP32 thermometer over Wi-Fi; phones, tablets and computers share a live browser view. No cloud account, frontend build or Python packages are required.

**Release history:** see [CHANGELOG.md](CHANGELOG.md). This repository contains the web application only. **Device firmware, compiled firmware, Wi-Fi credentials and personal measurement data are intentionally not distributed.**

## Documentation

- Companion firmware: [Thermal Probe](https://github.com/nenipresotReta/thermal-probe), distributed as source with local Wi-Fi configuration. The protocol below also permits an independent compatible device.
- [Deployment and recovery](docs/deployment.md): local/LAN setup, first-start checks, Docker backup/restore and troubleshooting.
- [Contributing and publication readiness](CONTRIBUTING.md): verification, license and privacy requirements.

## Run locally

Requires Python 3.11 or later:

```sh
python3 server.py
```

Open **http://localhost:8080**. On the first visit, **DEVICE** opens the connection dialog:

1. Enter the thermometer's IPv4 address and select **TEST**, then **CONNECT**.
2. Or enter its LAN subnet, for example `192.168.1.0/24`, select **DISCOVER**, then **USE DEVICE**.

Discovery checks both the compatible temperature HTTP endpoint and the Modbus register contract; it does not treat an arbitrary HTTP server as a thermometer. A scan is limited to a private IPv4 subnet of at most 256 addresses, with 16 concurrent probes. The subnet is where the **server** can reach devices; Docker networking or VLAN boundaries can prevent discovery. Manual entry works when the IP is reachable even if discovery does not.

The selected address is saved to `data/device.json` and reused on restart. The application never asks for the thermometer's Wi-Fi password. Failed connection tests preserve the current selection; finish an active recording or calibration before switching devices. Switching clears the live physical-model history so temperatures from different probes cannot form one forecast.

Optional startup overrides:

```sh
python3 server.py --device 192.168.1.100 --port 8080 --data ./data
```

Address precedence: explicit `--device`, saved device selection, then `DEVICE_HOST` as an initial default. The first version has one active thermometer; it is not a multi-device recording manager.

## Docker

```sh
cp .env.example .env
docker compose up -d --build
```

The default web binding is loopback. On a trusted home server, set `WEB_BIND=0.0.0.0` in `.env`, then open `http://SERVER_IP:8080` from other LAN devices. `DEVICE_HOST` can remain empty: select the thermometer in the web UI. The named `scope-data` volume retains the device selection, SQLite history, events and prediction scores.

The container runs as a non-root user. No USB mapping or firmware flashing is needed. The server must be able to reach the thermometer on TCP 502 and, for discovery, TCP 80. This version has no login or TLS termination; keep it on the intended home network.

## Appearance

Use **THEME** in the header to switch between **GitHub Dark** and the original **Paper** palette. GitHub Dark is the default; the selection is remembered in each browser and synchronized between its tabs. Chart grids, events, forecast shading and dialogs share the selected palette. Colors are inspired by [GitHub Primer](https://primer.style/product/primitives/color/) and match the companion thermometer display.

## Scope and recording

- **TIME / DIV** × 10 sets the visible time window. Default: 10 minutes, including 5 minutes of future forecast space.
- In **LIVE**, the mouse wheel changes only the temperature upper limit: **0–X°C**. It does not pan vertically, change the time window or pause acquisition.
- **0–250°C FIXED** restores that exact scale. **AUTO** remains an automatic visible-data range. In HOLD/archive, wheel zoom controls time; dragging pans history.
- **HOLD** freezes the view while background collection and storage continue. **LIVE** returns to current readings.
- D1 and D2 default to **°C/min and °C/min²**. Switch to °C/s and °C/s² with the units button; an explicitly saved browser choice is preserved. Stored values and the device protocol always use seconds. D1 is multiplied by 60 and D2 by 3600 for minute display.
- **START** opens a recording. **CHARGE**, **DRY END**, **FC START**, **FC END**, **SC START**, **DROP**, and custom events mark time and temperature. **DROP** ends the recording; acquisition continues.
- **ARCHIVE** opens saved recordings and CSV export. **FORECAST CSV** exports frozen predictions with parameter snapshots and later observations.

The collector targets 10 Hz using a persistent Modbus connection. Actual delivery depends on the network. Browser viewers share one collection stream via SSE and do not create separate thermometer connections.

## Thermodynamic forecast

The forecast is a **conditional, effective single-node thermal balance**:

```text
C dT/dt = P - G(T - Ta),  C > 0, G > 0
τ = C/G,  Teq = Ta + P/G
T(t+s) = T(t) + v0 τ [1 - exp(-s/τ)]
```

The hypothesis is that heat input `P`, heat transfer `G` and ambient temperature `Ta` remain locally constant for the forecast interval. Recent contiguous measurements identify the effective time constant and equilibrium. No manually named operating regime is required.

All horizons belong to the same thermal trajectory. Under this model, warming approaches equilibrium from below and cooling from above; the forecast cannot invent a future reversal. Recent observed reversals trigger re-identification, without rewriting earlier predictions. It does not anticipate future heater, airflow or probe-contact changes.

The default forecast is **5 minutes**, evaluated at approximately 10-second spacing, with exact additional short scoring horizons. Parameter uncertainty, near equilibrium and transients inconsistent with one node are explicitly labeled. Nearly linear or flat data cannot uniquely identify a distant equilibrium/time constant. The constant-net-heat limit is used when finite-time-constant fitting is unresolved; physically impossible long-horizon extrapolation is withheld.

This models the **smoothed probe reading**, including unseparated probe and filter lag. It does not identify actual bean/core temperature, material heat capacity, heater power or ambient temperature separately. The shaded envelope is parameter/residual sensitivity, **not a calibrated confidence interval**. Five-minute accuracy has not been established by a single warm/cool experiment.

Predictions and their parameter snapshots are frozen, then scored against later observations at +5, +10, +20, +30, +60, +180 and +300 seconds. Actual values are interpolated only across measurement gaps ≤0.5 seconds. Old model versions are excluded from current model scores.

## Optional probe response test

**CALIBRATE** supports a manual room-temperature ↔ well-mixed hot-water step. Select the destination WATER or AIR, start before transferring the sensing tip, and finish after settling. The fit requires a sufficient temperature step, duration and response quality; rejected attempts remain available to continue or cancel.

Air and water response results are saved separately. They do not automatically compensate temperatures or overwrite the effective forecast model. This measures response time, not sensor offset/gain accuracy. Probe material dimensions alone do not establish the complete internal response.

## Compatible thermometer contract

Bring your own compatible firmware; **no firmware artifacts or Wi-Fi configuration are supplied here**.

- Modbus TCP: port **502**, unit **1**, function **3**, zero-based registers.
- Four finite, big-endian Float32 values at register pairs **0** raw °C, **2** smoothed °C, **4** D1 °C/s, **6** D2 °C/s².
- A read of registers 0–7 returns byte count 16. Exception 4 is treated as sensor unavailable/warming up.
- Discovery additionally checks `GET /api/temperature` on TCP 80, returning JSON fields `valid`, `derivatives_ready`, `time_s`, `raw_c`, `temperature_c`, `d1_c_per_s`, `d2_c_per_s2`.

The device supplies derivative smoothing; the original target uses a roughly 10-second quadratic fit. This app preserves the received values rather than silently deriving different D1/D2 values.

## Storage and limits

SQLite WAL commits approximately once per second; abrupt power loss can lose the most recent uncommitted samples. Timestamps are server receipt times, not hardware acquisition timestamps. Browser reconnects restore shared recording state and backfill persisted history, even while the probe is offline. Live recording timers and freshness use server time advanced with a monotonic browser clock; a viewing device’s wall-clock setting does not change development ratios. There is no automatic retention/deletion policy yet, so monitor disk usage.

Use one collector process per database. To back up a running local instance consistently:

```sh
python3 -c "import sqlite3; a=sqlite3.connect('data/scope.sqlite3'); b=sqlite3.connect('backup.sqlite3'); a.backup(b); b.close(); a.close()"
```

Stop the collector before moving a database to a Docker volume; the container data directory must be writable by UID/GID 10001. Do not copy only the main file of a live WAL database. Historical sessions are retained when the selected device changes; start a new recording when changing probes. Forecasts are scored only against the device address that issued them. Earlier predictions with no recorded source remain preserved, but pending ones are not assigned to a new device. CSV exports stream in bounded chunks; user-entered event labels that could be spreadsheet formulas are escaped only in the export.

## Development and release checks

```sh
python3 -m unittest discover -s tests -v
for test in tests/*.test.js; do node "$test"; done
for file in static/*.js; do node --check "$file"; done
python3 tools/check_release.py
docker compose config -q
```

Node is only needed for development checks, not runtime. Tests cover device detection, bounded discovery, persistence, failed selection, Modbus fragmentation/reconnection, events/CSV, physical-model numerical integration and forecast scoring. GitHub Actions runs tests, a tracked-source audit and a fresh-container onboarding smoke test.

The release audit checks the staged snapshot and rejects tracked firmware, binaries, runtime databases, captures and detected credential patterns. `.gitignore` and `.dockerignore` exclude local runtime material. These safeguards supplement the explicit reviewed source-file list; they are not permission to add firmware or secrets.

References: [Artisan chart behavior](https://github.com/artisan-roaster-scope/artisan/blob/master/src/artisanlib/canvas.py), [MIT lumped thermal analysis](https://web.mit.edu/16.unified/www/FALL/thermodynamics/notes/node129.html). The implementation is independent; no Artisan source is bundled.

### Coffee and general recordings (v0.2)

Before START choose **COFFEE** or **GENERAL / NON-COFFEE**. Coffee enables phase marks, development time and optional AUTO DROP. General mode has manual custom events, no automatic detection and no coffee development/weight calculations.

In a recording, the time axis starts at **00:00**, initially spans **16 minutes**, and expands to retain the complete recording and forecast space. LIVE scroll still zooms temperature from zero; HOLD allows manual time inspection. Archive initially fits the whole recording.

After **FC START**, the prominent development display updates continuously: `(now − FC START) / (now − recording start) × 100%`. At DROP (or STOP without DROP) it freezes. The denominator is recording time, not a later CHARGE marker. Historical manual marks are retained exactly as entered.

**AUTO DROP** is a retrospective sudden-cooling heuristic, independently implemented with reference to Artisan's behavior. It does not predict the desired roast endpoint or control a heater. Eligible coffee recordings must be at least 7 minutes long with a recent raw temperature >=160°C. Half-second raw medians must show >=3°C total cooling and a sustained slope <=−0.8°C/s over >=2 s. A candidate then waits **20 seconds**, requires >=15°C net cooling, and is rejected on a >=5°C rebound, recovery near the previous peak, or acquisition gap >1 s. The final DROP is backdated to the preceding local peak, not the confirmation time. Dismiss a candidate with **IGNORE / DISABLE**, or switch AUTO DROP off. Archive → **UNDO AUTO DROP** reopens the latest automatically ended recording and disables automatic detection for that run; samples were never deleted. Earlier recordings cannot be reopened across newer sessions.

A temperature probe alone cannot distinguish an actual DROP from a long accidental probe removal with the same thermal trace. The confirmation delay filters short disturbances; manual control/correction remains available. Reboot clears an unconfirmed candidate rather than inventing an event across missing data.

For a completed coffee recording, Archive → **ADD WEIGHTS / EDIT WEIGHTS** stores green and roasted weights in grams. Weight loss is `(green − roasted) / green × 100%`; both values must be positive and roasted <= green. Values are optional, editable, clearable and persist with that recording. The CSV retains its existing seven-column sample format; weight metadata and development summaries are available in `/api/runs` and the Archive UI.

Behavior references: [Artisan auto-DROP explanation](https://github.com/artisan-roaster-scope/artisan/discussions/1159), [official source](https://github.com/artisan-roaster-scope/artisan/blob/master/src/artisanlib/canvas.py). No Artisan source implementation is included in this project.

## License

[MIT](LICENSE). See [third-party notices](THIRD_PARTY_NOTICES.md) for dependencies and references.
