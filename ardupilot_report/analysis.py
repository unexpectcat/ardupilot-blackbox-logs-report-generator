"""Deriving intervals/events from a LogData, and the automatic flight-health flags."""

from collections import namedtuple

import numpy as np

from .logdata import LogData, fmt_seconds, VIBE_WARN, VIBE_CRIT

# `category` groups flags that are the same *kind* of thing (e.g. every
# internal-error event shares category "Internal error") - the Summary map's
# sidebar shows one checkbox per category, labeled with how many occurred.
# `t` is the flight-timeline second the flag ties to, or None if the flag
# describes the whole flight rather than one instant (e.g. a voltage range) -
# only flags with a `t` get a dot on the map; the rest are listed as plain
# text below it.
Flag = namedtuple("Flag", ["severity", "text", "category", "t"], defaults=[None, None])


def armed_intervals(log: LogData):
    """Return list of (start_s, end_s) while the vehicle was armed."""
    arm_events = sorted(((t, bool(val)) for t, kind, val in log.events if kind == "arm"), key=lambda x: x[0])
    intervals = []
    start = None
    for t, armed in arm_events:
        if armed and start is None:
            start = t
        elif not armed and start is not None:
            intervals.append((start, t))
            start = None
    if start is not None:
        intervals.append((start, log.duration_s))
    return intervals


def is_armed_at(armed_ivals, t):
    return any(s <= t <= e for s, e in armed_ivals)


def rc_failsafe_windows(log: LogData):
    """Pair 'Throttle failsafe on'/'off' notices into (start, end) windows."""
    windows = []
    start = None
    for t, kind, val in log.events:
        if kind != "notice":
            continue
        low = str(val).lower()
        if "throttle failsafe on" in low:
            start = t
        elif "throttle failsafe off" in low and start is not None:
            windows.append((start, t))
            start = None
    if start is not None:
        windows.append((start, log.duration_s))
    return windows


def _mean_before(log, msgtype, col, t, lookback=3.0):
    if not log.has(msgtype, col):
        return None
    times = log.t(msgtype)
    vals = np.asarray(log.col(msgtype, col), dtype=float)
    mask = (times >= t - lookback) & (times <= t)
    if not np.any(mask):
        return None
    return float(np.nanmean(vals[mask]))


def mode_intervals(log: LogData):
    """Return list of (name, start_s, end_s) flight-mode intervals."""
    changes = [(t, num) for (t, kind, num) in log.events if kind == "mode"]
    if not changes:
        return []
    changes.sort(key=lambda x: x[0])
    out = []
    for i, (t, num) in enumerate(changes):
        end = changes[i + 1][0] if i + 1 < len(changes) else log.duration_s
        out.append((log.mode_name(num), t, end))
    return out


def analyze_flags(log: LogData):
    flags = []  # list[Flag]

    if log.has("VIBE"):
        for axis in ("VibeX", "VibeY", "VibeZ"):
            if log.has("VIBE", axis):
                vals = np.asarray(log.col("VIBE", axis), dtype=float)
                mx = float(np.nanmax(vals))
                sev = "critical" if mx >= VIBE_CRIT else "warning" if mx >= VIBE_WARN else None
                if sev:
                    t_peak = float(log.t("VIBE")[int(np.nanargmax(vals))])
                    thresh = VIBE_CRIT if sev == "critical" else VIBE_WARN
                    label = "critical" if sev == "critical" else "elevated"
                    flags.append(Flag(sev, f"{axis} vibration peaked at {mx:.1f} ({label}, >= {thresh:.0f})",
                                       f"{axis} vibration peak", t_peak))
        if log.has("VIBE", "Clip"):
            clip_vals = np.asarray(log.col("VIBE", "Clip"), dtype=float)
            clip_events = int(np.nanmax(clip_vals))
            if clip_events > 0:
                nz = np.flatnonzero(clip_vals > 0)
                t_clip = float(log.t("VIBE")[nz[0]]) if len(nz) else None
                flags.append(Flag("warning", f"Accelerometer clipping detected (clip counter reached {clip_events})",
                                   "Accelerometer clipping", t_clip))

    if log.has("BAT", "Volt"):
        vmin = float(np.nanmin(log.col("BAT", "Volt")))
        vmax = float(np.nanmax(log.col("BAT", "Volt")))
        flags.append(Flag("good", f"Battery voltage ranged {vmin:.2f} V - {vmax:.2f} V over the log"))
        if log.has("BAT", "RemPct"):
            rmin = float(np.nanmin(log.col("BAT", "RemPct")))
            rmax = float(np.nanmax(log.col("BAT", "RemPct")))
            if vmax > 0 and (vmax - vmin) / vmax > 0.15 and (rmax - rmin) <= 5:
                flags.append(Flag("warning",
                    f"Voltage dropped {vmax-vmin:.1f} V but reported remaining capacity barely moved "
                    f"({rmin:.0f}-{rmax:.0f}%) - check BATT_CAPACITY / battery monitor configuration"))

    if log.has("ARSP", "Airspeed") and log.nonzero("ARSP", "Airspeed"):
        pass
    elif log.has("CTUN", "As") and not log.nonzero("CTUN", "As"):
        flags.append(Flag("warning", "No usable airspeed sensor data found in this log"))

    if not log.has("GPS") and not log.has("POS"):
        flags.append(Flag("warning", "No GPS position data recorded in this log (GPS logging disabled, or no fix)"))
    elif log.has("GPS", "NSats"):
        sats = np.asarray(log.col("GPS", "NSats"), dtype=float)
        smin = float(np.nanmin(sats))
        if smin < 6:
            t_min = float(log.t("GPS")[int(np.nanargmin(sats))])
            flags.append(Flag("warning", f"GPS satellite count dropped as low as {smin:.0f} during the log",
                               "Low satellite count", t_min))

    errors = [(t, val) for t, kind, val in log.events if kind == "error"]
    if errors:
        sev = "serious" if len(errors) < 3 else "critical"
        for t, val in errors:
            flags.append(Flag(sev, str(val), "Internal error", t))

    failsafes = [(t, val) for t, kind, val in log.events
                 if kind == "notice" and "failsafe" in str(val).lower() and " on" in str(val).lower()]
    for t, val in failsafes:
        flags.append(Flag("serious", str(val), "Failsafe activation", t))

    armed_ivals = armed_intervals(log)
    for t_fs, _end in rc_failsafe_windows(log):
        if not is_armed_at(armed_ivals, t_fs):
            flags.append(Flag("good",
                f"Failsafe at {fmt_seconds(t_fs)} occurred while disarmed - most likely the transmitter "
                f"being switched off after landing, not a flight event",
                "RC failsafe (post-landing)", t_fs))
            continue
        lq = _mean_before(log, "RSSI", "RXLQ", t_fs)
        rssi = _mean_before(log, "RSSI", "RXRSSI", t_fs)
        if lq is not None and lq >= 90:
            detail = f"link quality was still {lq:.0f}%"
            if rssi is not None:
                detail += f" (RSSI {rssi:.2f})"
            flags.append(Flag("critical",
                f"In-flight RC failsafe at {fmt_seconds(t_fs)} was NOT preceded by a link-quality drop - {detail} "
                f"in the 3s before. Likely a brief packet/timeout glitch or receiver hiccup rather than "
                f"true out-of-range/weak signal - review RC_FS_TIMEOUT and the receiver/antenna setup "
                f"rather than assuming range loss.",
                "RC failsafe (steady link - glitch)", t_fs))
        else:
            flags.append(Flag("serious", f"In-flight RC failsafe at {fmt_seconds(t_fs)} followed a real link-quality drop"
                                          f"{f' (down to {lq:.0f}%)' if lq is not None else ''}",
                               "RC failsafe (link-quality drop)", t_fs))

    if not flags:
        flags.append(Flag("good", "No notable issues detected by the automatic checks"))

    return flags


def timestamped_categories(flags):
    """Group timestamped flags by category -> list[Flag], in first-seen order."""
    groups = {}
    for f in flags:
        if f.t is not None and f.category is not None:
            groups.setdefault(f.category, []).append(f)
    return groups


def untimestamped_flags(flags):
    return [f for f in flags if f.t is None]
