#!/usr/bin/env python3
"""
ArduPilot Dataflash Log Report Generator
=========================================

Reads a binary dataflash log (.BIN) written by ArduPilot (Plane/Copter/Rover/Sub)
- e.g. the ones found on the SD card of a Matek H743 flight controller under
APM/LOGS/ - and builds a readable, illustrated flight report with a GUI preview
and a "Save as PDF" button.

Usage:
    python3 ardupilot_log_report.py [path/to/log.BIN]

Requirements: pymavlink, numpy, matplotlib, PySide6.
"""

import os
import sys
import glob
import datetime

import numpy as np

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QToolBar, QPushButton,
    QCheckBox, QComboBox, QLabel, QSpinBox, QTabWidget, QFileDialog,
    QMessageBox,
)

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.backends.backend_pdf import PdfPages

from pymavlink import mavutil


# ---------------------------------------------------------------------------
# Palette / theming (validated categorical/status palette - see dataviz
# color-formula & palette.md). Chart colors (categorical hues + status) are
# frozen per light/dark mode - a surface adopts one theme and never mixes -
# so only light/dark switches them. The "color scheme" picker only changes
# the surrounding Qt chrome's accent color; it never touches chart data color.
# ---------------------------------------------------------------------------
CHART_THEMES = {
    "light": {
        "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "surface": "#fcfcfb",
        "hue": {"blue": "#2a78d6", "aqua": "#1baf7a", "yellow": "#eda100", "green": "#008300",
                "violet": "#4a3aa7", "red": "#e34948", "magenta": "#e87ba4", "orange": "#eb6834"},
    },
    "dark": {
        "ink": "#ffffff", "ink2": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "surface": "#1a1a19",
        "hue": {"blue": "#3987e5", "aqua": "#199e70", "yellow": "#c98500", "green": "#008300",
                "violet": "#9085e9", "red": "#e66767", "magenta": "#d55181", "orange": "#d95926"},
    },
}
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}  # fixed - never themed
# Categorical order, reordered so low-contrast "yellow" (relief rule: needs a direct
# label to read on the light surface) is not one of the first few lines in a busy chart.
CATEGORICAL_ORDER = ("blue", "aqua", "green", "violet", "red", "magenta", "orange", "yellow")

# Qt chrome (page plane / panel / border), from palette.md's chart-chrome-&-ink table.
CHROME_THEMES = {
    "light": {"page": "#f9f9f7", "panel": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e",
              "muted": "#898781", "border": "rgba(11,11,11,0.14)"},
    "dark": {"page": "#0d0d0d", "panel": "#1a1a19", "ink": "#ffffff", "ink2": "#c3c2b7",
             "muted": "#898781", "border": "rgba(255,255,255,0.14)"},
}
# Accent choices, each pulled straight from the validated categorical hues above
# (never an invented color) and checked for >=3:1 contrast against both surfaces.
ACCENT_THEMES = {
    "Ocean": {"light": "#2a78d6", "dark": "#3987e5"},
    "Ember": {"light": "#eb6834", "dark": "#d95926"},
    "Amethyst": {"light": "#4a3aa7", "dark": "#9085e9"},
}
FONT_FAMILIES = {
    "Sans Serif": ("sans-serif", QFont.StyleHint.SansSerif),
    "Serif": ("serif", QFont.StyleHint.Serif),
    "Monospace": ("monospace", QFont.StyleHint.Monospace),
    "Rounded": ("cursive", QFont.StyleHint.Cursive),
}

# Mutable "current" chart theme state - build_* functions below read these
# module globals directly, so re-assigning them here and calling
# apply_chart_theme() again is enough to re-theme every figure built after.
HUE = dict(CHART_THEMES["light"]["hue"])
LINE_CATEGORICAL = [HUE[k] for k in CATEGORICAL_ORDER]
INK = INK2 = MUTED = GRID = SURFACE = None


def apply_chart_theme(mode, font_family="Sans Serif", font_size=9):
    """Re-point the module-level chart color/font globals at `mode` ("light"/"dark")
    and push them into matplotlib's rcParams. Figures built after this call pick
    up the new theme; already-built Figure objects do not change retroactively."""
    global HUE, LINE_CATEGORICAL, INK, INK2, MUTED, GRID, SURFACE
    theme = CHART_THEMES[mode]
    HUE = dict(theme["hue"])
    LINE_CATEGORICAL = [HUE[k] for k in CATEGORICAL_ORDER]
    INK, INK2, MUTED, GRID, SURFACE = theme["ink"], theme["ink2"], theme["muted"], theme["grid"], theme["surface"]

    mpl_family, _ = FONT_FAMILIES.get(font_family, FONT_FAMILIES["Sans Serif"])
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK2,
        "text.color": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "grid.color": GRID,
        "axes.grid": True,
        "grid.linewidth": 0.6,
        "font.family": mpl_family,
        "font.size": font_size,
        "axes.titlesize": font_size + 2,
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.figsize": (10, 7.5),
    })


def build_stylesheet(mode, accent):
    """Qt stylesheet for the app chrome. Chart colors are untouched by this -
    only window/toolbar/tab/button/checkbox colors follow `mode` and `accent`."""
    c = CHROME_THEMES[mode]
    return f"""
    QMainWindow, QWidget {{ background: {c['page']}; color: {c['ink']}; }}
    QToolBar {{ background: {c['panel']}; border: none; border-bottom: 1px solid {c['border']};
                spacing: 8px; padding: 6px; }}
    QToolBar QLabel {{ color: {c['ink2']}; padding: 0 2px; }}
    QPushButton {{ background: {c['panel']}; color: {c['ink']}; border: 1px solid {c['border']};
                   border-radius: 6px; padding: 6px 14px; }}
    QPushButton:hover {{ border: 1px solid {accent}; color: {accent}; }}
    QPushButton:pressed {{ background: {accent}; color: white; }}
    QComboBox, QSpinBox {{ background: {c['panel']}; color: {c['ink']}; border: 1px solid {c['border']};
                            border-radius: 6px; padding: 4px 8px; min-height: 18px; }}
    QComboBox:hover, QSpinBox:hover {{ border: 1px solid {accent}; }}
    QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['ink']}; selection-background-color: {accent};
                                    selection-color: white; outline: none; }}
    QCheckBox {{ color: {c['ink']}; spacing: 6px; }}
    QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {c['border']}; border-radius: 3px;
                             background: {c['panel']}; }}
    QCheckBox::indicator:checked {{ background: {accent}; border: 1px solid {accent}; }}
    QCheckBox::indicator:hover {{ border: 1px solid {accent}; }}
    QLabel {{ color: {c['ink2']}; }}
    QLabel#status {{ color: {c['ink2']}; padding-left: 8px; }}
    QTabWidget::pane {{ border-top: 1px solid {c['border']}; background: {c['panel']}; }}
    QTabBar::tab {{ background: transparent; color: {c['ink2']}; padding: 8px 18px;
                    border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {c['ink']}; border-bottom: 2px solid {accent}; font-weight: 600; }}
    QTabBar::tab:hover {{ color: {c['ink']}; }}
    """


MODE_MAPS = {
    "Plane": mavutil.mode_mapping_apm,
    "Copter": mavutil.mode_mapping_acm,
    "Rover": mavutil.mode_mapping_rover,
    "Sub": mavutil.mode_mapping_sub,
}

VIBE_WARN, VIBE_CRIT = 30.0, 60.0          # ArduPilot rule-of-thumb thresholds (m/s/s)
BATT_WARN_CELL, BATT_CRIT_CELL = 3.5, 3.3  # volts/cell

apply_chart_theme("light")  # establish rcParams defaults before any Figure is built


def fmt_seconds(s):
    if s is None or np.isnan(s):
        return "n/a"
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:d}h {m:02d}m {sec:02d}s"
    return f"{m:d}m {sec:02d}s"


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Analysis / automatic flags
# ---------------------------------------------------------------------------
def analyze_flags(log: LogData):
    flags = []  # (severity, text)

    if log.has("VIBE"):
        for axis in ("VibeX", "VibeY", "VibeZ"):
            if log.has("VIBE", axis):
                mx = float(np.nanmax(log.col("VIBE", axis)))
                if mx >= VIBE_CRIT:
                    flags.append(("critical", f"{axis} vibration peaked at {mx:.1f} (critical, >= {VIBE_CRIT:.0f})"))
                elif mx >= VIBE_WARN:
                    flags.append(("warning", f"{axis} vibration peaked at {mx:.1f} (elevated, >= {VIBE_WARN:.0f})"))
        if log.has("VIBE", "Clip"):
            clip_events = int(np.nanmax(log.col("VIBE", "Clip")))
            if clip_events > 0:
                flags.append(("warning", f"Accelerometer clipping detected (clip counter reached {clip_events})"))

    if log.has("BAT", "Volt"):
        vmin = float(np.nanmin(log.col("BAT", "Volt")))
        vmax = float(np.nanmax(log.col("BAT", "Volt")))
        flags.append(("good", f"Battery voltage ranged {vmin:.2f} V - {vmax:.2f} V over the log"))
        if log.has("BAT", "RemPct"):
            rmin = float(np.nanmin(log.col("BAT", "RemPct")))
            rmax = float(np.nanmax(log.col("BAT", "RemPct")))
            if vmax > 0 and (vmax - vmin) / vmax > 0.15 and (rmax - rmin) <= 5:
                flags.append(("warning",
                    f"Voltage dropped {vmax-vmin:.1f} V but reported remaining capacity barely moved "
                    f"({rmin:.0f}-{rmax:.0f}%) - check BATT_CAPACITY / battery monitor configuration"))

    if log.has("ARSP", "Airspeed") and log.nonzero("ARSP", "Airspeed"):
        pass
    elif log.has("CTUN", "As") and not log.nonzero("CTUN", "As"):
        flags.append(("warning", "No usable airspeed sensor data found in this log"))

    if not log.has("GPS") and not log.has("POS"):
        flags.append(("warning", "No GPS position data recorded in this log (GPS logging disabled, or no fix)"))
    elif log.has("GPS", "NSats"):
        smin = float(np.nanmin(log.col("GPS", "NSats")))
        if smin < 6:
            flags.append(("warning", f"GPS satellite count dropped as low as {smin:.0f} during the log"))

    n_errors = sum(1 for e in log.events if e[1] == "error")
    if n_errors:
        flags.append(("serious" if n_errors < 3 else "critical", f"{n_errors} internal error event(s) logged"))

    failsafes = [e for e in log.events if e[1] == "notice" and "failsafe" in str(e[2]).lower() and " on" in str(e[2]).lower()]
    if failsafes:
        flags.append(("serious", f"{len(failsafes)} failsafe activation(s) logged"))

    armed_ivals = armed_intervals(log)
    for t_fs, _end in rc_failsafe_windows(log):
        if not is_armed_at(armed_ivals, t_fs):
            flags.append(("good",
                f"Failsafe at {fmt_seconds(t_fs)} occurred while disarmed - most likely the transmitter "
                f"being switched off after landing, not a flight event"))
            continue
        lq = _mean_before(log, "RSSI", "RXLQ", t_fs)
        rssi = _mean_before(log, "RSSI", "RXRSSI", t_fs)
        if lq is not None and lq >= 90:
            detail = f"link quality was still {lq:.0f}%"
            if rssi is not None:
                detail += f" (RSSI {rssi:.2f})"
            flags.append(("critical",
                f"In-flight RC failsafe at {fmt_seconds(t_fs)} was NOT preceded by a link-quality drop - {detail} "
                f"in the 3s before. Likely a brief packet/timeout glitch or receiver hiccup rather than "
                f"true out-of-range/weak signal - review RC_FS_TIMEOUT and the receiver/antenna setup "
                f"rather than assuming range loss."))
        else:
            flags.append(("serious", f"In-flight RC failsafe at {fmt_seconds(t_fs)} followed a real link-quality drop"
                                      f"{f' (down to {lq:.0f}%)' if lq is not None else ''}"))

    if not flags:
        flags.append(("good", "No notable issues detected by the automatic checks"))

    return flags


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


def _shade_failsafe_windows(axes, log, label_ax=None):
    """Shade RC-failsafe windows: solid red while armed (in-flight loss), gray while disarmed.

    If label_ax is given, an explicit "LOST RC LINK" label is stamped over each
    in-flight window on that axis so the event can't be missed.
    """
    windows = rc_failsafe_windows(log)
    if not windows:
        return False
    armed_ivals = armed_intervals(log)
    for ax in axes:
        for s, e in windows:
            end = max(e, s + 0.5)
            in_flight = is_armed_at(armed_ivals, s)
            color = STATUS["critical"] if in_flight else MUTED
            alpha = 0.30 if in_flight else 0.12
            ax.axvspan(s, end, color=color, alpha=alpha, lw=0, zorder=0)
            ax.axvline(s, color=color, ls="--", lw=1.3, zorder=1)
            ax.axvline(end, color=color, ls="--", lw=1.3, alpha=0.6, zorder=1)

    if label_ax is not None:
        trans = label_ax.get_xaxis_transform()
        for s, e in windows:
            if not is_armed_at(armed_ivals, s):
                continue
            mid = (s + max(e, s + 0.5)) / 2
            label_ax.text(mid, 0.95, "LOST RC LINK", transform=trans, ha="center", va="top",
                          fontsize=10, fontweight="bold", color=STATUS["critical"])
    return True


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


# ---------------------------------------------------------------------------
# Figure builders - each returns (title, matplotlib.figure.Figure) or None
# ---------------------------------------------------------------------------
def _blank_axis_message(ax, text):
    ax.axis("off")
    ax.text(0.5, 0.5, text, ha="center", va="center", color=MUTED, fontsize=11, wrap=True)


def build_summary(log: LogData, flags):
    fig = Figure()
    fig.suptitle("Flight Log Summary", fontsize=15, fontweight="bold", color=INK, x=0.03, ha="left")
    ax = fig.add_axes((0.04, 0.04, 0.92, 0.85))
    ax.axis("off")

    lines = []
    if len(log.paths) > 1:
        lines.append(f"Files: {os.path.basename(log.paths[0])} .. {os.path.basename(log.paths[-1])}, "
                      f"{len(log.paths)} logs merged into one timeline")
    else:
        lines.append(f"File: {os.path.basename(log.path)}")
    lines.append(f"Vehicle: {log.vehicle or 'Unknown'}    Firmware: {log.firmware or 'n/a'}")
    if log.board:
        lines.append(f"Board: {log.board}")
    if log.flight_window:
        lines.append(f"Flight duration: {fmt_seconds(log.duration_s)}, cropped from "
                      f"{fmt_seconds(log.logged_duration_s)} total logged - pre-arm/bench/idle time discarded")
    else:
        lines.append(f"Log duration: {fmt_seconds(log.duration_s)}")

    n_arms = sum(1 for e in log.events if e[1] == "arm" and e[2])
    n_modes = len(mode_intervals(log))
    lines.append(f"Arm events: {n_arms}    Flight-mode changes: {n_modes}")

    if log.has("BAT", "Volt"):
        lines.append(f"Battery: {np.nanmin(log.col('BAT','Volt')):.2f} - {np.nanmax(log.col('BAT','Volt')):.2f} V, "
                      f"peak current {np.nanmax(log.col('BAT','Curr')):.1f} A" if log.has("BAT", "Curr") else "")
    if log.has("CTUN", "Roll"):
        lines.append(f"Max roll: {np.nanmax(np.abs(log.col('CTUN','Roll'))):.1f} deg    "
                      f"Max pitch: {np.nanmax(np.abs(log.col('CTUN','Pitch'))):.1f} deg")

    y = 0.97
    for line in lines:
        if not line:
            continue
        ax.text(0, y, line, fontsize=11, color=INK, transform=ax.transAxes, va="top")
        y -= 0.065

    y -= 0.03
    ax.text(0, y, "Automatic checks", fontsize=12, fontweight="bold", color=INK, transform=ax.transAxes, va="top")
    y -= 0.07
    for sev, text in flags:
        color = STATUS.get(sev, INK2)
        marker = {"good": "OK", "warning": "!", "serious": "!!", "critical": "!!!"}.get(sev, "-")
        ax.text(0, y, marker, fontsize=11, fontweight="bold", color=color, transform=ax.transAxes, va="top")
        ax.text(0.06, y, text, fontsize=10.5, color=INK, transform=ax.transAxes, va="top", wrap=True)
        y -= 0.06
        if y < 0.02:
            break
    return "Summary", fig


def build_modes(log: LogData):
    intervals = mode_intervals(log)
    if not intervals:
        return None

    armed_ivals = armed_intervals(log)
    fs_row_name = "RC FAILSAFE"
    fs_intervals = [(s, max(e, s + 0.5)) for s, e in rc_failsafe_windows(log) if is_armed_at(armed_ivals, s)]

    fig = Figure()
    ax = fig.add_axes((0.20, 0.15, 0.76, 0.75))
    names = sorted({name for name, _, _ in intervals})
    y_of = {n: i for i, n in enumerate(names)}
    for name, s, e in intervals:
        color = LINE_CATEGORICAL[y_of[name] % len(LINE_CATEGORICAL)]
        ax.barh(y_of[name], e - s, left=s, height=0.6, color=color, edgecolor="none")

    if fs_intervals:
        fs_row = len(names)
        for s, e in fs_intervals:
            ax.barh(fs_row, e - s, left=s, height=0.6, color=STATUS["critical"], edgecolor="none")
        names = names + [fs_row_name]

    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names)
    for tick_label, name in zip(ax.get_yticklabels(), names):
        if name == fs_row_name:
            tick_label.set_color(STATUS["critical"])
            tick_label.set_fontweight("bold")
    ax.set_xlabel("Time (s)")
    ax.set_title("Flight mode timeline")
    ax.set_xlim(0, log.duration_s)
    return "Flight Modes", fig


def build_events_table(log: LogData):
    rows = []
    for t, kind, val in log.events:
        if kind == "mode":
            rows.append((t, "Mode", log.mode_name(val)))
        elif kind == "arm":
            rows.append((t, "Arm", "ARMED" if val else "DISARMED"))
        elif kind == "error":
            rows.append((t, "Error", str(val)))
        elif kind == "notice":
            rows.append((t, "Notice", str(val)))
    if not rows:
        return None
    rows.sort(key=lambda r: r[0])

    fig = Figure(figsize=(10, max(3, 0.28 * min(len(rows), 40) + 1)))
    ax = fig.add_axes((0.02, 0.02, 0.96, 0.92))
    ax.axis("off")
    ax.set_title(f"Events & errors ({len(rows)} total)", loc="left")
    shown = rows[:40]
    table_data = [[fmt_seconds(r[0]), r[1], r[2]] for r in shown]
    tbl = ax.table(cellText=table_data, colLabels=["Time", "Type", "Detail"],
                    loc="upper left", cellLoc="left", colWidths=[0.12, 0.13, 0.75])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1, 1.25)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor(GRID)
        if r == 0:
            cell.set_facecolor("#efeeea")
            cell.set_text_props(fontweight="bold", color=INK)
        else:
            cell.set_facecolor(SURFACE)
    if len(rows) > 40:
        fig.text(0.02, 0.01, f"... and {len(rows) - 40} more (see PDF export for the full list)",
                  fontsize=8, color=MUTED)
    return "Events", fig


def events_pdf_pages(log: LogData, page_rows=35):
    """Yield full-page Figures covering ALL events, for PDF export."""
    rows = []
    for t, kind, val in log.events:
        if kind == "mode":
            rows.append((t, "Mode", log.mode_name(val)))
        elif kind == "arm":
            rows.append((t, "Arm", "ARMED" if val else "DISARMED"))
        elif kind == "error":
            rows.append((t, "Error", str(val)))
        elif kind == "notice":
            rows.append((t, "Notice", str(val)))
    if not rows:
        return
    rows.sort(key=lambda r: r[0])
    for i in range(0, len(rows), page_rows):
        chunk = rows[i:i + page_rows]
        fig = Figure(figsize=(8.5, 11))
        ax = fig.add_axes((0.05, 0.05, 0.9, 0.88))
        ax.axis("off")
        ax.set_title(f"Events & errors  (page {i // page_rows + 1})", loc="left")
        table_data = [[fmt_seconds(r[0]), r[1], r[2]] for r in chunk]
        tbl = ax.table(cellText=table_data, colLabels=["Time", "Type", "Detail"],
                        loc="upper left", cellLoc="left", colWidths=[0.14, 0.16, 0.68])
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(9)
        tbl.scale(1, 1.4)
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor(GRID)
            cell.set_facecolor("#efeeea" if r == 0 else SURFACE)
            if r == 0:
                cell.set_text_props(fontweight="bold", color=INK)
        yield fig


def _has_signal(log, mt, c):
    """True if the column exists and is not just a constant-zero placeholder."""
    return log.has(mt, c) and log.nonzero(mt, c)


def _stack_plot(log, specs, xlabel="Time (s)"):
    """specs: list of (title, [(msgtype, col, label, color)], ylabel)"""
    specs = [s for s in specs if any(_has_signal(log, mt, c) for mt, c, *_ in s[1])]
    if not specs:
        return None
    fig = Figure()
    axes = fig.subplots(len(specs), 1, sharex=True)
    if len(specs) == 1:
        axes = [axes]
    for ax, (title, series, ylabel) in zip(axes, specs):
        any_plotted = False
        for i, (mt, c, label, color) in enumerate(series):
            if not _has_signal(log, mt, c):
                continue
            ax.plot(log.t(mt), log.col(mt, c), lw=1.1, color=color, label=label)
            any_plotted = True
        if not any_plotted:
            _blank_axis_message(ax, "No data")
            continue
        ax.set_title(title, loc="left", fontsize=10)
        ax.set_ylabel(ylabel)
        if len(series) > 1:
            ax.legend(loc="upper right", fontsize=8, frameon=False)
    axes[-1].set_xlabel(xlabel)
    axes[-1].set_xlim(0, log.duration_s)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    return fig


def build_altitude_airspeed(log: LogData):
    specs = [
        ("Altitude", [
            ("POS", "RelHomeAlt", "Rel. altitude (POS)", HUE["blue"]),
            ("BARO", "Alt", "Barometric altitude", HUE["aqua"]),
        ], "meters"),
        ("Airspeed", [
            ("ARSP", "Airspeed", "Airspeed (sensor)", HUE["violet"]),
            ("CTUN", "As", "Airspeed (control loop)", HUE["orange"]),
        ], "m/s"),
        ("Climb / groundspeed", [
            ("GPS", "Spd", "Ground speed", HUE["green"]),
            ("GPS", "VZ", "Vertical speed", HUE["red"]),
        ], "m/s"),
    ]
    fig = _stack_plot(log, specs)
    if fig is None:
        return None
    return "Altitude & Airspeed", fig


def build_attitude(log: LogData):
    specs = [
        ("Roll", [("ATT", "Roll", "Actual", HUE["blue"]), ("ATT", "DesRoll", "Desired", HUE["orange"])], "deg"),
        ("Pitch", [("ATT", "Pitch", "Actual", HUE["blue"]), ("ATT", "DesPitch", "Desired", HUE["orange"])], "deg"),
        ("Yaw / heading", [("ATT", "Yaw", "Actual", HUE["blue"]), ("ATT", "DesYaw", "Desired", HUE["orange"])], "deg"),
    ]
    fig = _stack_plot(log, specs)
    if fig is None:
        return None
    return "Attitude", fig


def build_pids(log: LogData):
    specs = []
    for axis, mt in (("Roll", "PIDR"), ("Pitch", "PIDP"), ("Yaw", "PIDY")):
        series = []
        for col, label, hue in (("Des", "Desired rate", "orange"), ("P", "P term", "blue"),
                                 ("I", "I term", "aqua"), ("D", "D term", "violet"), ("FF", "FF term", "green")):
            series.append((mt, col, label, HUE[hue]))
        specs.append((f"{axis} rate controller", series, ""))
    fig = _stack_plot(log, specs)
    if fig is None:
        return None
    return "PID Tuning", fig


def build_battery(log: LogData):
    specs = [
        ("Voltage", [("BAT", "Volt", "Battery voltage", HUE["blue"]), ("BAT", "VoltR", "Sag-resistant estimate", HUE["aqua"])], "V"),
        ("Current", [("BAT", "Curr", "Current draw", HUE["red"])], "A"),
        ("Remaining capacity", [("BAT", "RemPct", "Remaining", HUE["green"])], "%"),
    ]
    fig = _stack_plot(log, specs)
    if fig is None:
        return None
    return "Battery & Power", fig


def build_rc_servo(log: LogData):
    if not (log.has("RCIN") or log.has("RCOU")):
        return None
    fig = Figure()
    ax1, ax2 = fig.subplots(2, 1, sharex=True)
    plotted1 = plotted2 = False
    if log.has("RCIN"):
        for i in range(1, 5):
            c = f"C{i}"
            if log.has("RCIN", c):
                ax1.plot(log.t("RCIN"), log.col("RCIN", c), lw=1, color=LINE_CATEGORICAL[i - 1], label=f"RC{i} in")
                plotted1 = True
    if plotted1:
        ax1.set_title("RC input (channels 1-4)", loc="left", fontsize=10)
        ax1.set_ylabel("PWM (us)")
        ax1.legend(loc="upper right", fontsize=8, frameon=False)
    else:
        _blank_axis_message(ax1, "No RC input data")

    if log.has("RCOU"):
        for i in range(1, 7):
            c = f"C{i}"
            if log.has("RCOU", c):
                ax2.plot(log.t("RCOU"), log.col("RCOU", c), lw=1, color=LINE_CATEGORICAL[(i - 1) % len(LINE_CATEGORICAL)], label=f"Servo {i}")
                plotted2 = True
    if plotted2:
        ax2.set_title("Servo / motor output (channels 1-6)", loc="left", fontsize=10)
        ax2.set_ylabel("PWM (us)")
        ax2.legend(loc="upper right", fontsize=8, ncol=2, frameon=False)
    else:
        _blank_axis_message(ax2, "No servo output data")

    ax2.set_xlabel("Time (s)")
    ax2.set_xlim(0, log.duration_s)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    return "RC & Servos", fig


def build_rc_link(log: LogData):
    if not (log.has("RSSI") or log.has("RCIN")):
        return None

    fig = Figure()
    ax1, ax2 = fig.subplots(2, 1, sharex=True)

    plotted = False
    if log.has("RSSI", "RXLQ"):
        ax1.plot(log.t("RSSI"), log.col("RSSI", "RXLQ"), lw=1.1, color=HUE["aqua"], label="Link quality (%)")
        plotted = True
    if log.has("RSSI", "RXRSSI"):
        rssi = np.asarray(log.col("RSSI", "RXRSSI"), dtype=float)
        rssi_pct = rssi * 100.0 if np.nanmax(rssi) <= 1.0 else rssi
        ax1.plot(log.t("RSSI"), rssi_pct, lw=1.1, color=HUE["blue"], label="RSSI (scaled)")
        plotted = True
    if plotted:
        ax1.set_title("RC link quality / RSSI, with failsafe windows shaded", loc="left", fontsize=10)
        ax1.set_ylabel("%")
        ax1.set_ylim(0, 105)
        ax1.legend(loc="lower left", fontsize=8, frameon=False)
    else:
        _blank_axis_message(ax1, "No RSSI/link-quality data")

    plotted2 = False
    if log.has("RCIN"):
        for i in range(1, 5):
            c = f"C{i}"
            if log.has("RCIN", c):
                ax2.plot(log.t("RCIN"), log.col("RCIN", c), lw=1, color=LINE_CATEGORICAL[i - 1], label=f"RC{i} in")
                plotted2 = True
    if plotted2:
        ax2.set_title("RC input channels", loc="left", fontsize=10)
        ax2.set_ylabel("PWM (us)")
        ax2.legend(loc="upper right", fontsize=8, ncol=4, frameon=False)
    else:
        _blank_axis_message(ax2, "No RC input data")

    ax2.set_xlabel("Time (s)")
    ax2.set_xlim(0, log.duration_s)
    has_windows = _shade_failsafe_windows([ax1, ax2], log, label_ax=ax1)
    fig.tight_layout(rect=(0, 0, 1, 0.95 if has_windows else 0.97))
    if has_windows:
        fig.text(0.01, 0.005, "Shading: red = failsafe while armed, gray = failsafe while disarmed",
                  fontsize=7.5, color=MUTED)
    return "RC Link (ELRS)", fig


def build_vibration(log: LogData):
    if not log.has("VIBE"):
        return None
    fig = Figure()
    axes = fig.subplots(2, 1, sharex=True)
    ax = axes[0]
    for axis, hue in (("VibeX", "blue"), ("VibeY", "aqua"), ("VibeZ", "violet")):
        if log.has("VIBE", axis):
            ax.plot(log.t("VIBE"), log.col("VIBE", axis), lw=0.8, color=HUE[hue], label=axis)
    ax.axhline(VIBE_WARN, color=STATUS["warning"], ls="--", lw=1, label="Warning level")
    ax.axhline(VIBE_CRIT, color=STATUS["critical"], ls="--", lw=1, label="Critical level")
    ax.set_title("Vibration levels", loc="left", fontsize=10)
    ax.set_ylabel("m/s/s")
    ax.legend(loc="upper right", fontsize=8, ncol=2, frameon=False)

    ax2 = axes[1]
    if log.has("VIBE", "Clip"):
        ax2.plot(log.t("VIBE"), log.col("VIBE", "Clip"), lw=1, color=HUE["red"])
        ax2.set_title("Accelerometer clip count (cumulative)", loc="left", fontsize=10)
        ax2.set_ylabel("count")
    else:
        _blank_axis_message(ax2, "No clip-count data")
    ax2.set_xlabel("Time (s)")
    ax2.set_xlim(0, log.duration_s)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    return "Vibration & IMU", fig


def build_system_health(log: LogData):
    specs = [
        ("Main loop load", [("PM", "Load", "Load", HUE["blue"])], "%"),
        ("Link quality", [("RSSI", "RXLQ", "Link quality", HUE["aqua"]), ("RSSI", "RXRSSI", "RSSI", HUE["orange"])], ""),
    ]
    fig = _stack_plot(log, specs)
    if fig is None:
        return None
    return "System Health", fig


def build_gps_track(log: LogData):
    have_gps = log.has("GPS", "Lat") and log.nonzero("GPS", "Lat")
    have_pos = log.has("POS", "Lat") and log.nonzero("POS", "Lat")
    if not (have_gps or have_pos):
        fig = Figure()
        ax = fig.add_axes((0.1, 0.1, 0.8, 0.8))
        _blank_axis_message(ax, "No GPS position data was recorded in this log.")
        return "GPS Track", fig

    mt = "GPS" if have_gps else "POS"
    lat, lng = log.col(mt, "Lat"), log.col(mt, "Lng")
    fig = Figure()
    ax = fig.add_axes((0.12, 0.12, 0.8, 0.8))
    ax.plot(lng, lat, lw=1.2, color=HUE["blue"])
    ax.scatter([lng[0]], [lat[0]], color=STATUS["good"], zorder=5, label="Start")
    ax.scatter([lng[-1]], [lat[-1]], color=STATUS["critical"], zorder=5, label="End")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Ground track")
    ax.set_aspect("equal", adjustable="datalim")
    ax.legend(loc="best", fontsize=8, frameon=False)
    return "GPS Track", fig


BUILDERS = [
    build_modes,
    build_altitude_airspeed,
    build_attitude,
    build_pids,
    build_battery,
    build_rc_servo,
    build_rc_link,
    build_vibration,
    build_system_health,
    build_gps_track,
    build_events_table,
]


def build_report(log: LogData):
    """Returns ordered list of (title, Figure) for on-screen display."""
    flags = analyze_flags(log)
    pages = [build_summary(log, flags)]
    for builder in BUILDERS:
        result = builder(log)
        if result is not None:
            pages.append(result)
    return pages, flags


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
SD_GLOBS = [
    "/run/media/*/*/APM/LOGS",
    "/media/*/*/APM/LOGS",
    "/media/*/APM/LOGS",
    "/Volumes/*/APM/LOGS",
]


def find_sd_logs_dir():
    for pattern in SD_GLOBS:
        for d in sorted(glob.glob(pattern)):
            if glob.glob(os.path.join(d, "*.BIN")) or glob.glob(os.path.join(d, "*.bin")):
                return d
    return None


def _log_number(p):
    stem = os.path.splitext(os.path.basename(p))[0]
    return int(stem) if stem.isdigit() else -1


def discover_logs_in_dir(directory):
    """All .BIN/.bin logs in a directory, in flight order (by numeric filename).

    Dataflash SD cards commonly have no working RTC, so every file's mtime is
    identical (e.g. 1980-01-01) - filesystem "latest" is meaningless here; the
    zero-padded log number is the only reliable chronological order.
    """
    files = glob.glob(os.path.join(directory, "*.BIN")) + glob.glob(os.path.join(directory, "*.bin"))
    return sorted(files, key=_log_number)


MERGED_LABEL = "All logs in folder (merged flight)"


class ReportApp(QMainWindow):
    def __init__(self, initial_path=None):
        super().__init__()
        self.setWindowTitle("ArduPilot Log Report")
        self.resize(1320, 860)

        self.log = None
        self.pages = []
        self.flags = []
        self.current_dir = find_sd_logs_dir() or os.path.expanduser("~")
        self._choice_dir = self.current_dir

        # Appearance state: chart colors follow mode only (never the accent -
        # a chart surface freezes one theme); accent/font are pure Qt chrome.
        self.mode = "light"
        self.accent = "Ocean"
        self.font_family = "Sans Serif"
        self.font_size = 9

        self.notebook = QTabWidget()
        self.setCentralWidget(self.notebook)

        self._build_toolbar()
        self._apply_stylesheet()
        self._apply_font()
        self._show_placeholder()

        if initial_path:
            if isinstance(initial_path, list):
                self.load_log(initial_path)
            elif os.path.isdir(initial_path):
                logs = discover_logs_in_dir(initial_path)
                if logs:
                    self.load_log(logs if len(logs) > 1 else logs[0])
                else:
                    QMessageBox.critical(self, "No logs found", f"No .BIN log files were found in:\n{initial_path}")
            elif os.path.isfile(initial_path):
                self.load_log(initial_path)
            else:
                QMessageBox.critical(
                    self, "Path not found",
                    f"Could not find:\n{initial_path}\n\n"
                    "If the folder or file name contains spaces, quote it, e.g.:\n"
                    '  python3 ardupilot_log_report.py "path/with spaces/APM/LOGS"',
                )
        else:
            # Nothing is auto-loaded from the filesystem: the user picks the
            # folder explicitly, so the tool never has to guess at (or silently
            # read) files the user didn't point it at.
            QTimer.singleShot(150, self.on_select_folder)

    def _build_toolbar(self):
        bar = QToolBar("Main")
        bar.setMovable(False)
        self.addToolBar(bar)

        btn_folder = QPushButton("Select Folder...")
        btn_folder.clicked.connect(self.on_select_folder)
        bar.addWidget(btn_folder)

        btn_open = QPushButton("Open File(s)...")
        btn_open.clicked.connect(self.on_open)
        bar.addWidget(btn_open)

        btn_pdf = QPushButton("Save as PDF")
        btn_pdf.clicked.connect(self.on_save_pdf)
        bar.addWidget(btn_pdf)

        bar.addSeparator()

        self.crop_check = QCheckBox("Crop to flight only (arm-disarm)")
        self.crop_check.setChecked(True)
        self.crop_check.stateChanged.connect(self.on_crop_toggle)
        bar.addWidget(self.crop_check)

        bar.addSeparator()

        bar.addWidget(QLabel("Log:"))
        self.log_choice = QComboBox()
        self.log_choice.setMinimumWidth(220)
        self.log_choice.currentTextChanged.connect(self.on_choice_selected)
        bar.addWidget(self.log_choice)

        bar.addSeparator()

        bar.addWidget(QLabel("Mode:"))
        self.mode_choice = QComboBox()
        self.mode_choice.addItems(["Light", "Dark"])
        self.mode_choice.currentTextChanged.connect(self.on_mode_changed)
        bar.addWidget(self.mode_choice)

        bar.addWidget(QLabel("Scheme:"))
        self.accent_choice = QComboBox()
        self.accent_choice.addItems(list(ACCENT_THEMES.keys()))
        self.accent_choice.currentTextChanged.connect(self.on_accent_changed)
        bar.addWidget(self.accent_choice)

        bar.addWidget(QLabel("Font:"))
        self.font_choice = QComboBox()
        self.font_choice.addItems(list(FONT_FAMILIES.keys()))
        self.font_choice.currentTextChanged.connect(self.on_font_changed)
        bar.addWidget(self.font_choice)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(7, 16)
        self.size_spin.setValue(self.font_size)
        self.size_spin.setSuffix(" pt")
        self.size_spin.valueChanged.connect(self.on_font_size_changed)
        bar.addWidget(self.size_spin)

        bar.addSeparator()

        self.status_label = QLabel("No log loaded.")
        self.status_label.setObjectName("status")
        bar.addWidget(self.status_label)

    def _apply_stylesheet(self):
        accent = ACCENT_THEMES[self.accent][self.mode]
        self.setStyleSheet(build_stylesheet(self.mode, accent))

    def _apply_font(self):
        family, style_hint = FONT_FAMILIES[self.font_family]
        font = QFont(family)
        font.setStyleHint(style_hint)
        font.setPointSize(self.font_size + 1)
        app = QApplication.instance()
        app.setFont(font)
        for w in self.findChildren(QWidget):
            w.setFont(font)
        self.setFont(font)

    def _rebuild_pages(self):
        """Re-render figures from the already-parsed log under the current
        chart theme/font - no re-parsing of the log file(s) needed."""
        if self.log is None:
            return
        self.pages, self.flags = build_report(self.log)
        self._populate_tabs()

    def on_mode_changed(self, text):
        self.mode = text.lower()
        apply_chart_theme(self.mode, self.font_family, self.font_size)
        self._apply_stylesheet()
        self._rebuild_pages()

    def on_accent_changed(self, text):
        self.accent = text
        self._apply_stylesheet()

    def on_font_changed(self, text):
        self.font_family = text
        apply_chart_theme(self.mode, self.font_family, self.font_size)
        self._apply_font()
        self._rebuild_pages()

    def on_font_size_changed(self, value):
        self.font_size = value
        apply_chart_theme(self.mode, self.font_family, self.font_size)
        self._apply_font()
        self._rebuild_pages()

    def _show_placeholder(self):
        self._clear_tabs()
        frame = QWidget()
        layout = QVBoxLayout(frame)
        msg = QLabel(
            "Click \"Select Folder...\" and choose the folder that contains your\n"
            "ArduPilot .BIN dataflash logs (e.g. the SD card's APM/LOGS folder).\n\n"
            "All .BIN files found there are merged into one timeline. By default\n"
            "it's cropped to the longest continuous armed period (flight-only); untick\n"
            "\"Crop to flight only\" in the toolbar to benchmark the full log instead."
        )
        layout.addWidget(msg, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addStretch()
        self.notebook.addTab(frame, "Start")

    def on_select_folder(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Select folder containing ArduPilot .BIN logs", self.current_dir,
        )
        if not directory:
            return
        logs = discover_logs_in_dir(directory)
        if not logs:
            # SD cards typically nest logs under APM/LOGS - check one level down before giving up.
            nested = glob.glob(os.path.join(directory, "*", "LOGS")) + glob.glob(os.path.join(directory, "*", "*", "LOGS"))
            for d in nested:
                logs = discover_logs_in_dir(d)
                if logs:
                    directory = d
                    break
        if not logs:
            QMessageBox.information(self, "No logs found", f"No .BIN log files were found in:\n{directory}")
            return
        self.current_dir = directory
        self.load_log(logs if len(logs) > 1 else logs[0])

    def _refresh_log_choice(self):
        directory = os.path.dirname(self.log.paths[-1]) if self.log else self.current_dir
        files = discover_logs_in_dir(directory)
        names = [os.path.basename(f) for f in files]
        values = ([MERGED_LABEL] if len(files) > 1 else []) + names

        self.log_choice.blockSignals(True)
        self.log_choice.clear()
        self.log_choice.addItems(values)
        if self.log:
            if len(self.log.paths) > 1:
                self.log_choice.setCurrentText(MERGED_LABEL)
            else:
                base = os.path.basename(self.log.path)
                if base in names:
                    self.log_choice.setCurrentText(base)
        self.log_choice.blockSignals(False)
        self._choice_dir = directory

    def on_choice_selected(self, name):
        if not name:
            return
        if name == MERGED_LABEL:
            self.load_log(discover_logs_in_dir(self._choice_dir))
            return
        path = os.path.join(self._choice_dir, name)
        if self.log and self.log.paths == [path]:
            return
        self.load_log(path)

    def on_open(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open ArduPilot dataflash log(s) - select multiple to merge one flight",
            self.current_dir, "ArduPilot log (*.bin *.BIN);;All files (*)",
        )
        if paths:
            self.load_log(sorted(paths, key=_log_number) if len(paths) > 1 else paths[0])

    def on_crop_toggle(self):
        if self.log is not None:
            self.load_log(list(self.log.paths))

    def load_log(self, path_or_paths):
        paths = [path_or_paths] if isinstance(path_or_paths, str) else list(path_or_paths)
        label = f"{len(paths)} logs" if len(paths) > 1 else os.path.basename(paths[0])
        self.status_label.setText(f"Parsing {label} ...")
        QApplication.processEvents()
        try:
            log = LogData(paths, crop_to_flight=self.crop_check.isChecked())
            pages, flags = build_report(log)
        except Exception as exc:
            QMessageBox.critical(self, "Failed to parse log", str(exc))
            self.status_label.setText("Failed to parse log.")
            return

        self.log, self.pages, self.flags = log, pages, flags
        self.current_dir = os.path.dirname(paths[-1])
        self._populate_tabs()
        self._refresh_log_choice()

        n_flags = sum(1 for s, _ in flags if s in ("warning", "serious", "critical"))
        crop_note = ""
        if log.flight_window:
            crop_note = f" (cropped from {fmt_seconds(log.logged_duration_s)} logged)"
        self.status_label.setText(
            f"{label}  |  {log.vehicle or 'Unknown vehicle'}  |  "
            f"flight {fmt_seconds(log.duration_s)}{crop_note}  |  {n_flags} flag(s) raised"
        )

    def _clear_tabs(self):
        while self.notebook.count():
            w = self.notebook.widget(0)
            self.notebook.removeTab(0)
            w.deleteLater()

    def _populate_tabs(self):
        self._clear_tabs()
        for title, fig in self.pages:
            frame = QWidget()
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(0, 0, 0, 0)
            canvas = FigureCanvasQTAgg(fig)
            toolbar = NavigationToolbar2QT(canvas, frame)
            layout.addWidget(toolbar)
            layout.addWidget(canvas)
            canvas.draw()
            self.notebook.addTab(frame, title)

    def on_save_pdf(self):
        if not self.log:
            QMessageBox.information(self, "No log loaded", "Open a log file first.")
            return
        default_name = os.path.splitext(os.path.basename(self.log.path))[0] + "_report.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save flight report as PDF", os.path.join(self.current_dir, default_name),
            "PDF document (*.pdf)",
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self._export_pdf(path)
        except Exception as exc:
            QMessageBox.critical(self, "Failed to save PDF", str(exc))
            return
        QMessageBox.information(self, "Saved", f"Report saved to:\n{path}")

    def _export_pdf(self, path):
        with PdfPages(path) as pdf:
            meta = pdf.infodict()
            meta["Title"] = f"ArduPilot Flight Report - {os.path.basename(self.log.path)}"
            meta["Author"] = "ardupilot_log_report.py"
            meta["CreationDate"] = datetime.datetime.now()

            for title, fig in self.pages:
                if title == "Events":
                    continue  # replaced below with full pagination
                pdf.savefig(fig)
            for fig in events_pdf_pages(self.log):
                pdf.savefig(fig)


def _resolve_cli_path(argv):
    """Recover a path argument from argv, tolerating shells that split an
    unquoted folder/file name containing spaces into several argv entries
    (e.g. a folder named "first flight ardu" typed without quotes).

    Returns None (no args), a single path string, a list of path strings
    (several explicit files given, to merge as one flight), or - if nothing
    resolves - the best-guess joined string so the caller can report it.
    """
    args = argv[1:]
    if not args:
        return None
    if len(args) == 1:
        return args[0]

    joined = os.path.expanduser(" ".join(args))
    if os.path.exists(joined):
        return joined

    expanded = [os.path.expanduser(a) for a in args]
    if all(os.path.exists(a) for a in expanded):
        return expanded

    return joined


def main():
    initial = _resolve_cli_path(sys.argv)
    app = QApplication(sys.argv)
    window = ReportApp(initial_path=initial)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
