# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A single-file Python Prometheus exporter (`byd_hvs_hvm_exporter.py`) that polls a BYD HVS/HVM home battery over TCP/Modbus and exposes metrics on an HTTP endpoint. The only runtime dependency is `prometheus_client`. Distribution is via Docker image published to `ghcr.io/hkuehl/byd-hvs-hvm-prometheus-exporter`.

## Common commands

Run locally (requires reachable battery):
```
pip install prometheus_client
BATTERY_IP=192.168.2.22 BATTERY_PORT=8080 PROMETHEUS_PORT=3425 POLLING_INTERVAL=30 python byd_hvs_hvm_exporter.py
```

Run via docker-compose (edit `BATTERY_IP` first):
```
docker compose up --build
```

Build and publish image (per README):
```
docker build . -t ghcr.io/hkuehl/byd-hvs-hvm-prometheus-exporter:latest
export CR_PAT=<github PAT>
echo $CR_PAT | docker login ghcr.io -u hkuehl --password-stdin
docker push ghcr.io/hkuehl/byd-hvs-hvm-prometheus-exporter:latest
```

CI (`.github/workflows/docker-publish.yml`) builds and pushes the image to `ghcr.io/${{ github.repository }}:latest` on every push/PR to `main`.

There is no test suite, no linter config, and no `requirements.txt`.

## Architecture

The exporter runs an infinite polling loop. Each cycle opens a fresh TCP socket to the battery, walks a fixed state machine that sends preformatted Modbus frames, decodes the byte-aligned responses, then publishes to Prometheus and sleeps `POLLING_INTERVAL` seconds.

**State machine** (constants `STATE_START` → `STATE_FINISH` in `byd_hvs_hvm_exporter.py`):
1. `MESSAGE_0` → `decode_packet0`: serial, firmware, module count, grid type, battery type (HVS/LVS via byte 5 of serial).
2. `MESSAGE_1` → `decode_packet1`: SOC, SOH, voltages, current, temps. Stored in module-level globals (`hvsSOC`, `hvsMaxVolt`, …).
3. `MESSAGE_2` → `decode_packet2`: derives `hvsNumCells` and `hvsNumTemps` from battery type + module count. `MESSAGE_3` then primes a measurement.
4. Wait `waitTime` (3 s) for measurement, then `MESSAGE_4` arms readout.
5. `MESSAGE_5`–`MESSAGE_8` + `MESSAGE_12` → `decode_packet5/6/7/8` and `decode_response12`: per-cell voltages (cells 1–16, 17–80, 81–128, 129+) and per-cell-group temperatures, written into `towerAttributes[0]`.
6. `update_prometheus_metrics()` flushes globals + `towerAttributes[0]` into the module-level `Gauge`/`Counter` objects, then sleeps.

**Important coupling points to know before editing decode logic:**
- Decoded values live in two places: top-level globals (set by `decode_packet1`) and `towerAttributes[0]` dict (set by `decode_packet5+`). `update_prometheus_metrics` reads from both — adding a metric usually means touching both.
- `towerAttributes` is a `[{}]` (single-tower assumption); the codebase is not multi-tower-ready despite the `tower="0"` Prometheus label.
- Cell-index ranges are hard-coded and assume HVS module sizing (16 cells per packet5, 17–80 per packet6, 81–128 per packet7, 129+ per response12). LVS sizing is partially handled in `decode_packet2` but not throughout.
- `MESSAGE_5` through `MESSAGE_12` are intentionally identical hex strings — the battery returns different payloads as it streams measurement data; do not "deduplicate" them.
- `modbus_crc`, `buf2int16SI` (signed big-endian), and `buf2int32US` (the unusual byte order `[2][3][0][1]`) are battery-protocol-specific; reuse them rather than rewriting.
- `charge_total_counter` / `discharge_total_counter` are `Counter`s but are `.inc()`-ed with the absolute reading each cycle, which is incorrect Counter semantics — be aware before "fixing" it that downstream dashboards may already account for this.

**Configuration** is entirely environment-variable driven (`BATTERY_IP`, `BATTERY_PORT`, `PROMETHEUS_PORT`, `POLLING_INTERVAL`); defaults in code target `192.168.2.22:8080` and serve metrics on `:3425`.
