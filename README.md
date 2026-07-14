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
- Runs automatic checks and calls out anything worth a human's attention:
  elevated/critical vibration, accelerometer clipping, battery voltage vs.
  reported-remaining-capacity mismatches, missing GPS/airspeed data, and RC
  failsafes - including whether a failsafe was preceded by an actual
  link-quality drop or looks like a brief packet/timeout glitch instead.
- Exports the whole report (including every events-table page) to a single
  PDF.

## Requirements

- Python 3.9+
- [`pymavlink`](https://pypi.org/project/pymavlink/), `numpy`, `matplotlib`
- `tkinter` (ships with most Python installs; on Debian/Ubuntu: `sudo apt install python3-tk`)

Install the Python dependencies:

```bash
pip install pymavlink numpy matplotlib
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
