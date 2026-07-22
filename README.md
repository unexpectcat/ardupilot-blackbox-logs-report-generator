# ArduPilot Flight Log Report

A desktop tool that turns ArduPilot dataflash logs (`.BIN` files, e.g. from the
SD card of a Matek H743 or any other ArduPilot flight controller) into a
readable, illustrated flight report - with a GUI preview and a one-click
**Save as PDF**.

## What it does

- Reads one or more `.BIN` dataflash logs with [pymavlink](https://github.com/ArduPilot/pymavlink).
- ArduPilot starts a new log file on every reboot/power-cycle, so a single real
  flight is often split across several files. Point the tool at the folder
  containing them and it merges every `.BIN` file into one continuous
  timeline, then automatically crops the result down to the single longest
  continuous **armed** period - the actual flight - discarding bench
  arm/disarm blips and ground idle time before/after it.
- Builds a tabbed report: Summary, Flight Modes, Altitude & Airspeed,
  Attitude, PID Tuning, Battery & Power, RC & Servos, RC Link (ELRS),
  Vibration & IMU, System Health, GPS Track, and a full Events/Errors table.
- The **Summary** tab shows a map with the flight trajectory colored per
  flight mode, drawn over live OpenStreetMap tiles fetched for the flight's
  bounding box. Automatic-check flags that have a timestamp (e.g.
  "Accelerometer clipping detected") appear as dots on the map with a
  leader-lined label; a **Flag categories** toggle opens a sidebar to
  show/hide each category by checkbox. Flags with no single timestamp (e.g.
  a battery voltage range for the whole flight) are listed in a plain text
  panel below the map, shown by default. If the aircraft has no GPS at all,
  the map falls back to the local EKF-relative position estimate with no
  basemap; if the OSM tile fetch fails (offline, blocked, timeout) the map
  still draws the trajectory and flags on a plain themed background.
- Runs automatic checks and calls out anything worth a human's attention:
  elevated/critical vibration, accelerometer clipping, battery voltage vs.
  reported-remaining-capacity mismatches, missing GPS/airspeed data, and RC
  failsafes - including whether a failsafe was preceded by an actual
  link-quality drop or looks like a brief packet/timeout glitch instead.
- Exports the whole report (including every events-table page) to a single
  PDF.

- Toolbar controls for Light/Dark mode, a Color scheme accent (Ocean/Ember/
  Amethyst), and a font family/size picker.
- A **Crop to flight only** toggle: on by default (flight-only debugging); untick
  it to keep the full merged log, armed or not, for ground-bench benchmarking.

## Requirements

- Python 3.9+
- [`pymavlink`](https://pypi.org/project/pymavlink/), `numpy`, `matplotlib`, `PySide6`

Install the Python dependencies:

```bash
pip install pymavlink numpy matplotlib PySide6
```

## Usage

```bash
python3 ardupilot_log_report.py
```

No file is read automatically - on launch (or via the **Select Folder...**
button) a folder picker opens. Choose the folder that holds your `.BIN` logs
(e.g. the SD card's `APM/LOGS` folder, or a local copy of it). Every `.BIN`
file in that folder is merged and cropped as described above.

- **Select Folder...** - pick a folder; all `.BIN`/`.bin` files inside are
  merged into one flight.
- **Open File(s)...** - pick one specific log, or multi-select several to
  merge manually.
- The **Log:** dropdown lets you switch between the merged view and any
  individual file in the same folder.
- **Save as PDF** - exports the currently loaded report.

You can also pass a path directly:

```bash
python3 ardupilot_log_report.py /path/to/APM/LOGS       # merges every log in the folder
python3 ardupilot_log_report.py /path/to/00000014.BIN   # opens a single log
```

## Notes

- Nothing is scanned or read from your filesystem until you explicitly select
  a folder or file - the tool does not look for SD cards or logs on its own.
- Generated PDF reports contain your flight telemetry and are not written
  anywhere by default beyond the location you choose in the save dialog.
- The Summary tab's map fetches basemap tiles from `tile.openstreetmap.org`
  over the network whenever a log has GPS data - this is the only network
  access the tool makes. It's best-effort: a fetch failure just falls back to
  a plain themed background, and tiles are cached in-process so switching
  Light/Dark/font/accent doesn't re-fetch them. No new pip dependency was
  added for this - tiles are fetched with the standard library and decoded
  with matplotlib's own PNG reader.
