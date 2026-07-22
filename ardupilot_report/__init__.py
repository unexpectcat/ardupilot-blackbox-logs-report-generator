"""
ArduPilot Flight Log Report Generator
=========================================

Reads a binary dataflash log (.BIN) written by ArduPilot (Plane/Copter/Rover/Sub)
- e.g. the ones found on the SD card of a Matek H743 flight controller under
APM/LOGS/ - or a .tlog MAVLink telemetry log recorded by a ground station, and
builds a readable, illustrated flight report with a GUI preview and a "Save as
PDF" button.
"""

from .gui import main

__all__ = ["main"]
