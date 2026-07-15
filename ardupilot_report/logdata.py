"""Dataflash log parsing: turns one or more .BIN files into LogData."""

import numpy as np
from pymavlink import mavutil

MODE_MAPS = {
    "Plane": mavutil.mode_mapping_apm,
    "Copter": mavutil.mode_mapping_acm,
    "Rover": mavutil.mode_mapping_rover,
    "Sub": mavutil.mode_mapping_sub,
}

VIBE_WARN, VIBE_CRIT = 30.0, 60.0          # ArduPilot rule-of-thumb thresholds (m/s/s)
BATT_WARN_CELL, BATT_CRIT_CELL = 3.5, 3.3  # volts/cell


def fmt_seconds(s):
    if s is None or np.isnan(s):
        return "n/a"
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:d}h {m:02d}m {sec:02d}s"
    return f"{m:d}m {sec:02d}s"


class LogData:
    """Parses one or more .BIN dataflash logs into per-message-type numpy columns.

    ArduPilot starts a new log file on every reboot/power-cycle, so a single
    real-world flight session is often split across several files with each
    file's own clock restarting at zero. Passing a list of paths here
    concatenates them into one continuous timeline (sorted, offset end-to-end),
    then crops the result down to the single longest continuous armed interval -
    i.e. the actual flight - discarding bench arm/disarm blips and any idle
    ground time before/after it.
    """

    def __init__(self, paths, crop_to_flight=True):
        self.paths = [paths] if isinstance(paths, str) else list(paths)
        self.path = self.paths[-1]
        self.messages = {}      # type -> {col: np.array}
        self.vehicle = None
        self.firmware = ""
        self.board = ""
        self.events = []        # (t_sec, kind, value)
        self.duration_s = 0.0
        self.logged_duration_s = 0.0   # full merged duration before any cropping
        self.flight_window = None      # (start_s, end_s) in the pre-crop timeline, if cropped
        self._parse()
        if crop_to_flight:
            self._crop_to_longest_flight()

    def _parse(self):
        buf = {}
        offset = 0.0
        for path in self.paths:
            mlog = mavutil.mavlink_connection(path, dialect="ardupilotmega")
            t0 = None
            file_end = 0.0
            while True:
                msg = mlog.recv_match(blocking=False)
                if msg is None:
                    break
                t = msg.get_type()
                if t in ("BAD_DATA", "FMT", "FMTU", "UNIT", "MULT"):
                    continue
                d = msg.to_dict()
                d.pop("mavpackettype", None)
                if "TimeUS" in d:
                    if t0 is None:
                        t0 = d["TimeUS"]
                    local_t = (d["TimeUS"] - t0) / 1e6
                    d["_t"] = offset + local_t
                    file_end = max(file_end, local_t)

                col = buf.setdefault(t, {})
                for k, v in d.items():
                    col.setdefault(k, []).append(v)

                if t == "MSG":
                    self._handle_msg_text(d.get("_t", 0.0), str(d.get("Message", "")))
                elif t == "ERR":
                    self.events.append((d.get("_t", 0.0), "error",
                                         f"Error: subsystem {d.get('Subsys')} code {d.get('ECode')}"))
                elif t == "MODE":
                    self.events.append((d.get("_t", 0.0), "mode", int(d.get("Mode", -1))))
                elif t == "ARM":
                    armed = d.get("ArmState", d.get("Arm", None))
                    self.events.append((d.get("_t", 0.0), "arm", armed))
            offset += file_end

        self.messages = {t: {k: np.asarray(v) for k, v in cols.items()} for t, cols in buf.items()}
        self.duration_s = offset
        self.logged_duration_s = offset
        self.events.sort(key=lambda e: e[0])

    def _crop_to_longest_flight(self):
        from .analysis import armed_intervals

        intervals = armed_intervals(self)
        if not intervals:
            return
        start, end = max(intervals, key=lambda iv: iv[1] - iv[0])
        if end - start < 1.0:
            return  # nothing that looks like a real flight - leave uncropped

        # Carry the flight mode active at the moment of arming forward, so cropping
        # doesn't leave the start of the flight with no mode-timeline bar at all.
        prior_modes = [(t, val) for (t, kind, val) in self.events if kind == "mode" and t <= start]
        carry_mode = max(prior_modes, key=lambda tv: tv[0])[1] if prior_modes else None

        for cols in self.messages.values():
            if "_t" not in cols:
                continue
            mask = (cols["_t"] >= start) & (cols["_t"] <= end)
            for k in list(cols.keys()):
                cols[k] = cols[k][mask]
            cols["_t"] = cols["_t"] - start

        self.events = [(t - start, kind, val) for (t, kind, val) in self.events if start <= t <= end]
        if carry_mode is not None:
            self.events.insert(0, (0.0, "mode", carry_mode))
        self.flight_window = (start, end)
        self.duration_s = end - start

    def _handle_msg_text(self, t, txt):
        low = txt.lower()
        if not self.vehicle:
            for name in MODE_MAPS:
                if name.lower() in low:
                    self.vehicle = name
                    self.firmware = txt
                    break
        if "matek" in low or ("chibios" in low and not self.board):
            if not self.board or "matek" in low:
                self.board = txt if "matek" in low else self.board
        if any(k in low for k in ("failsafe", "armed", "disarmed", "crash", "ekf", "gps glitch", "err ")):
            self.events.append((t, "notice", txt))

    # -- accessors -----------------------------------------------------
    def has(self, msgtype, col=None):
        d = self.messages.get(msgtype)
        if d is None:
            return False
        if col is None:
            return True
        if col not in d:
            return False
        arr = np.asarray(d[col])
        if np.issubdtype(arr.dtype, np.number):
            return bool(np.any(np.isfinite(arr.astype(float))))
        return True

    def col(self, msgtype, col):
        return self.messages[msgtype][col]

    def t(self, msgtype):
        return self.messages[msgtype]["_t"]

    def nonzero(self, msgtype, col):
        """True if the column exists and has real (non-constant-zero) variation."""
        if not self.has(msgtype, col):
            return False
        v = np.asarray(self.messages[msgtype][col], dtype=float)
        return np.nanmax(v) != 0 or np.nanmin(v) != 0

    def mode_name(self, num):
        m = MODE_MAPS.get(self.vehicle, {})
        return m.get(num, f"MODE {num}")
