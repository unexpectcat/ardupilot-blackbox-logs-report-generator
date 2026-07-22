#!/usr/bin/env python3
"""
ArduPilot Flight Log Report Generator
=========================================

Reads a binary dataflash log (.BIN) written by ArduPilot (Plane/Copter/Rover/Sub)
- e.g. the ones found on the SD card of a Matek H743 flight controller under
APM/LOGS/ - or a .tlog MAVLink telemetry log recorded by a ground station, and
builds a readable, illustrated flight report with a GUI preview and a "Save as
PDF" button.

Usage:
    python3 ardupilot_log_report.py [path/to/log.BIN or log.tlog]

Requirements: pymavlink, numpy, matplotlib, PySide6.

Implementation lives in the ardupilot_report/ package alongside this file;
this script is just the documented entry point.
"""

from ardupilot_report.gui import main

if __name__ == "__main__":
    main()
