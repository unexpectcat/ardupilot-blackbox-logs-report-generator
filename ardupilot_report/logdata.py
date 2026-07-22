"""Log parsing: turns one or more .BIN dataflash logs, or .tlog MAVLink
telemetry logs, into a LogData with the same internal message schema."""

import math

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

# -- .tlog (MAVLink telemetry stream) support ---------------------------
#
# .tlog files have no dataflash-style FMT-defined message schema - they're a
# raw timestamped stream of standard MAVLink messages. `_parse_tlog_file`
# below translates the telemetry messages that carry the same information
# into the same synthetic message-type/column names the rest of this app
# already expects from a real dataflash log (GPS, ATT, BAT, VIBE, ...), so
# analysis.py/figures.py/summary_map.py need no tlog-specific code at all.
#
# HEARTBEAT.type -> the vehicle-family string MODE_MAPS is keyed by (values
# not listed - gimbals, GCS, antenna trackers, etc. - are simply ignored).
MAV_TYPE_VEHICLE = {
    1: "Plane", 19: "Plane", 20: "Plane", 21: "Plane",         # FIXED_WING, VTOL_DUO/QUAD/TILTROTOR
    2: "Copter", 3: "Copter", 4: "Copter", 13: "Copter",       # QUADROTOR, COAXIAL, HELICOPTER, HEXAROTOR
    14: "Copter", 15: "Copter", 29: "Copter",                  # OCTOROTOR, TRICOPTER, DODECAROTOR
    10: "Rover", 11: "Rover",                                  # GROUND_ROVER, SURFACE_BOAT
    12: "Sub",                                                 # SUBMARINE
}
MAV_MODE_FLAG_SAFETY_ARMED = 128
MAV_SEVERITY_ERROR_CUTOFF = 3   # MAV_SEVERITY: EMERGENCY/ALERT/CRITICAL/ERROR -> treated as a dataflash ERR event

# axis -> synthetic PID message type, mirroring ArduPilot's own PIDR/PIDP/PIDY dataflash split
PID_TUNING_AXIS_TYPE = {1: "PIDR", 2: "PIDP", 3: "PIDY"}

# Fixed column set per synthetic type synthesized from tlog telemetry. Every
# emitted row fills every column (nan where the MAVLink message that
# triggered this particular row didn't carry it), so a type's columns always
# stay the same length no matter which message contributed a given row -
# e.g. both SYS_STATUS and BATTERY_STATUS feed "BAT", ATTITUDE and
# NAV_CONTROLLER_OUTPUT both feed "ATT".
TLOG_SCHEMAS = {
    "GPS": ("Lat", "Lng", "NSats", "Spd"),
    "POS": ("Lat", "Lng", "RelHomeAlt"),
    "ATT": ("Roll", "Pitch", "Yaw", "DesRoll", "DesPitch", "DesYaw"),
    "PIDR": ("Des", "P", "I", "D", "FF"),
    "PIDP": ("Des", "P", "I", "D", "FF"),
    "PIDY": ("Des", "P", "I", "D", "FF"),
    "VIBE": ("VibeX", "VibeY", "VibeZ", "Clip"),
    "BAT": ("Volt", "Curr", "RemPct"),
    "ARSP": ("Airspeed",),
    "CTUN": ("As", "Roll", "Pitch"),
    "BARO": ("Alt",),
    "RCIN": ("C1", "C2", "C3", "C4"),
    "RCOU": ("C1", "C2", "C3", "C4", "C5", "C6"),
    "RSSI": ("RXLQ", "RXRSSI"),
    "XKF1": ("PN", "PE"),
}


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
    """Parses one or more .BIN dataflash logs or .tlog telemetry logs into
    per-message-type numpy columns.

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
            if path.lower().endswith(".tlog"):
                file_end = self._parse_tlog_file(path, buf, offset)
            else:
                file_end = self._parse_dataflash_file(path, buf, offset)
            offset += file_end

        self.messages = {t: {k: np.asarray(v) for k, v in cols.items()} for t, cols in buf.items()}
        self.duration_s = offset
        self.logged_duration_s = offset
        self.events.sort(key=lambda e: e[0])

    def _parse_dataflash_file(self, path, buf, offset):
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
        return file_end

    def _emit_tlog_row(self, buf, synth_type, t_abs, values):
        """Append one row to a synthetic dataflash-style message type, filling
        every column in its fixed schema (nan if `values` doesn't have it) so
        the type's columns always stay the same length - see TLOG_SCHEMAS."""
        col = buf.setdefault(synth_type, {})
        for k in TLOG_SCHEMAS[synth_type]:
            v = values.get(k)
            col.setdefault(k, []).append(float(v) if v is not None else float("nan"))
        col.setdefault("_t", []).append(t_abs)

    def _parse_tlog_file(self, path, buf, offset):
        mlog = mavutil.mavlink_connection(path, dialect="ardupilotmega")
        t0 = None
        file_end = 0.0
        last_mode = None
        last_armed = None
        while True:
            msg = mlog.recv_match(blocking=False)
            if msg is None:
                break
            mtype = msg.get_type()
            if mtype == "BAD_DATA":
                continue
            ts = getattr(msg, "_timestamp", None)
            if ts is None:
                continue
            if t0 is None:
                t0 = ts
            local_t = ts - t0
            file_end = max(file_end, local_t)
            t_abs = offset + local_t
            d = msg.to_dict()

            if mtype == "HEARTBEAT":
                if d.get("autopilot") == mavutil.mavlink.MAV_AUTOPILOT_INVALID:
                    continue  # a GCS/companion-computer heartbeat, not the autopilot's own
                veh = MAV_TYPE_VEHICLE.get(d.get("type"))
                if veh and not self.vehicle:
                    self.vehicle = veh
                armed = bool(d.get("base_mode", 0) & MAV_MODE_FLAG_SAFETY_ARMED)
                if armed != last_armed:
                    self.events.append((t_abs, "arm", armed))
                    last_armed = armed
                mode = d.get("custom_mode")
                if mode is not None and mode != last_mode:
                    self.events.append((t_abs, "mode", int(mode)))
                    last_mode = mode
            elif mtype == "STATUSTEXT":
                text = str(d.get("text", "")).strip("\x00").strip()
                self._handle_msg_text(t_abs, text)
                if d.get("severity", 99) <= MAV_SEVERITY_ERROR_CUTOFF:
                    self.events.append((t_abs, "error", f"Error: {text}"))
            elif mtype == "GPS_RAW_INT":
                if d.get("lat") or d.get("lon"):
                    vel = d.get("vel")
                    nsats = d.get("satellites_visible")
                    self._emit_tlog_row(buf, "GPS", t_abs, {
                        "Lat": d["lat"] / 1e7, "Lng": d["lon"] / 1e7,
                        "NSats": nsats if nsats != 255 else None,
                        "Spd": vel / 100.0 if vel is not None and vel != 65535 else None,
                    })
            elif mtype == "GLOBAL_POSITION_INT":
                if d.get("lat") or d.get("lon"):
                    self._emit_tlog_row(buf, "POS", t_abs, {
                        "Lat": d["lat"] / 1e7, "Lng": d["lon"] / 1e7,
                        "RelHomeAlt": d.get("relative_alt", 0) / 1000.0,
                    })
            elif mtype == "LOCAL_POSITION_NED":
                # Used by summary_map.py as the "no GPS installed" local-position
                # fallback, same as a real log's XKF1/NKF1 PN/PE.
                self._emit_tlog_row(buf, "XKF1", t_abs, {"PN": d.get("x"), "PE": d.get("y")})
            elif mtype == "ATTITUDE":
                roll, pitch = math.degrees(d["roll"]), math.degrees(d["pitch"])
                self._emit_tlog_row(buf, "ATT", t_abs, {
                    "Roll": roll, "Pitch": pitch, "Yaw": math.degrees(d["yaw"]) % 360,
                })
                self._emit_tlog_row(buf, "CTUN", t_abs, {"Roll": roll, "Pitch": pitch})
            elif mtype == "NAV_CONTROLLER_OUTPUT":
                self._emit_tlog_row(buf, "ATT", t_abs, {
                    "DesRoll": d.get("nav_roll"), "DesPitch": d.get("nav_pitch"), "DesYaw": d.get("nav_bearing"),
                })
            elif mtype == "PID_TUNING":
                synth = PID_TUNING_AXIS_TYPE.get(d.get("axis"))
                if synth:
                    self._emit_tlog_row(buf, synth, t_abs, {
                        "Des": d.get("desired"), "P": d.get("P"), "I": d.get("I"),
                        "D": d.get("D"), "FF": d.get("FF"),
                    })
            elif mtype == "VIBRATION":
                self._emit_tlog_row(buf, "VIBE", t_abs, {
                    "VibeX": d.get("vibration_x"), "VibeY": d.get("vibration_y"), "VibeZ": d.get("vibration_z"),
                    "Clip": max(d.get("clipping_0", 0), d.get("clipping_1", 0), d.get("clipping_2", 0)),
                })
            elif mtype == "SYS_STATUS":
                volt, curr, rem = d.get("voltage_battery"), d.get("current_battery"), d.get("battery_remaining")
                self._emit_tlog_row(buf, "BAT", t_abs, {
                    "Volt": volt / 1000.0 if volt not in (None, 65535) else None,
                    "Curr": curr / 100.0 if curr not in (None, -1) else None,
                    "RemPct": rem if rem not in (None, -1) else None,
                })
            elif mtype == "BATTERY_STATUS":
                volts = [v / 1000.0 for v in d.get("voltages", []) if v not in (0, 65535)]
                curr, rem = d.get("current_battery"), d.get("battery_remaining")
                self._emit_tlog_row(buf, "BAT", t_abs, {
                    "Volt": sum(volts) if volts else None,
                    "Curr": curr / 100.0 if curr not in (None, -1) else None,
                    "RemPct": rem if rem not in (None, -1) else None,
                })
            elif mtype == "VFR_HUD":
                self._emit_tlog_row(buf, "ARSP", t_abs, {"Airspeed": d.get("airspeed")})
                self._emit_tlog_row(buf, "CTUN", t_abs, {"As": d.get("airspeed")})
                self._emit_tlog_row(buf, "BARO", t_abs, {"Alt": d.get("alt")})
            elif mtype == "RC_CHANNELS":
                self._emit_tlog_row(buf, "RCIN", t_abs,
                                     {f"C{i}": d.get(f"chan{i}_raw") for i in range(1, 5)})
                rssi = d.get("rssi")
                self._emit_tlog_row(buf, "RSSI", t_abs, {
                    "RXRSSI": (rssi / 254.0 * 100.0) if rssi not in (None, 255) else None,
                })
            elif mtype == "SERVO_OUTPUT_RAW":
                self._emit_tlog_row(buf, "RCOU", t_abs,
                                     {f"C{i}": d.get(f"servo{i}_raw") for i in range(1, 7)})
        return file_end

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
