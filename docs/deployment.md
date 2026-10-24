# Deployment and recovery

[English](deployment.md) | [简体中文](deployment.zh-CN.md)

Thermal Scope is the server/browser application; [Thermal Probe](https://github.com/nenipresotReta/thermal-probe) is the companion ESP32 firmware. Neither project needs the other's build tools. The server reads the thermometer; browsers read the server. A browser does not connect directly to the ESP32.

## Choose a deployment

| Use | Start | Open |
|---|---|---|
| One computer | `python3 server.py` | `http://localhost:8080` |
| Trusted LAN, without Docker | `python3 server.py --bind 0.0.0.0` | `http://SERVER_IP:8080` |
| Docker, local access | `docker compose up -d --build` | `http://localhost:8080` |
| Docker, LAN access | Set `WEB_BIND=0.0.0.0` in `.env`, then start Compose | `http://SERVER_IP:WEB_PORT` |

Clone/check out the desired version before running these commands from the repository root. Python runtime requires 3.11+; Node is needed only for development tests. Docker requires Docker Engine and the Compose plugin. The Docker image is built from source; no published container registry image is assumed.

## First-start acceptance

1. Start the server and open the page. DEVICE should offer manual IPv4 entry or discovery.
2. TEST the probe, then CONNECT. Wait for the probe's derivative window if it has just booted.
3. Verify live temperature, D1/D2 and advancing sample time. Device discovery runs from the server's network, not the browser's network.
4. Create a short GENERAL recording, add an event, STOP, and open it in ARCHIVE. Export CSV and check the duration/event.
5. Restart the server and confirm the recording and selected device remain available.

Docker health means the HTTP service answers; it does not prove the probe is reachable. Verify probe status in the UI separately.

## Settings

| Setting | Meaning |
|---|---|
| `WEB_BIND` in `.env` | Host interface for Docker's published port; loopback by default |
| `WEB_PORT` in `.env` | Host web port, 8080 by default |
| `DEVICE_HOST` | Initial fallback probe address; may remain empty |
| `POLL_INTERVAL` | Collector target seconds between polls, default 0.1 |
| Local `--bind`, `--port`, `--data`, `--interval` | Server interface, port, storage directory and polling interval |
| Local `--device` | Explicit startup device override |

Selected device precedence is explicit `--device`, saved `data/device.json`, then `DEVICE_HOST`. Editing `DEVICE_HOST` does not replace an already saved selection. Use DEVICE to change it after ending an active recording/calibration. Docker mounts its named volume at `/data`.

The server must reach TCP 502 on the probe; discovery also needs TCP 80. Viewers need only the server web port. There is no login, authorization or TLS in the application. On a shared/untrusted network, provide access control outside the application; do not port-forward it directly to the internet.

## Back up and restore Docker data

For a simple consistent full-volume backup, finish recordings/calibration and stop the service first. These commands use a temporary Python container to create an archive on standard output, avoiding a host bind mount:

```sh
mkdir -p backups
chmod 700 backups
umask 077
docker compose stop thermal-scope
docker compose run --rm --no-deps -T thermal-scope python -c   'import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode="w|"); t.add("/data",arcname="data"); t.close()' > backups/scope-data.tar
docker compose up -d
```

Check the command exit status and inspect the archive before treating it as a backup. It includes private recordings and device configuration; keep it outside Git and restrict access. Do not run `docker compose down -v` unless intentionally deleting the data volume.

To restore **your own trusted backup** to an empty/new data volume, first stop the service. Restoration can overwrite files; retain the old volume/backup until verification is complete:

```sh
docker compose stop thermal-scope
docker compose run --rm --no-deps -T thermal-scope python -c   'import sys,tarfile; t=tarfile.open(fileobj=sys.stdin.buffer,mode="r|*"); t.extractall("/",filter="data")' < backups/scope-data.tar
docker compose up -d
```

The archive layout is `data/...`, restored into `/data`; files must be writable by container UID/GID 10001. Use the same Compose project name/directory when accessing an existing volume. Confirm ARCHIVE contents and device selection after recovery. The README also provides SQLite's online backup method for a local instance; a database-only backup does not include device selection.

## Upgrades and faults

Finish recordings, retain a backup and the previous source/image, then check out the new version and run `docker compose up -d --build`. Verify both HTTP health and live measurements. Schema migrations may make an old application incompatible with the new database: rollback should restore the matching pre-upgrade backup as well as the old version, accepting loss of later data.

| Symptom | Check |
|---|---|
| Other devices cannot open the page | Loopback vs LAN binding, host port and host firewall |
| Empty discovery result | Server subnet, routing/VLAN/isolation; try manual IPv4 entry |
| Connected probe but no values yet | Derivative warm-up; sensor validity; Modbus contract |
| Interrupted curve | Probe/network availability; server resource/disk status; inspect a short redacted log |
| Container healthy but readings stopped | Health is HTTP-only; check the device connection separately |
| Archive missing after redeploy | Compose project/volume identity and mounted `/data`; do not initialize over the original volume |

One active probe and one collector per database are supported. There is no automatic retention policy; monitor disk growth and back up valuable sessions.
