"""Figure builders - each returns (title, matplotlib.figure.Figure) or None.

Chart colors come from `theme.HUE` / `theme.STATUS` / `theme.INK` etc., read as
module-attribute lookups (`theme.HUE`, never `from .theme import HUE`) so that
a later `theme.apply_chart_theme(...)` call is picked up by every builder here.
"""

import os

import numpy as np
from matplotlib.figure import Figure

from . import theme
from .logdata import LogData, fmt_seconds, VIBE_WARN, VIBE_CRIT
from .analysis import analyze_flags, armed_intervals, is_armed_at, rc_failsafe_windows, mode_intervals


def _blank_axis_message(ax, text):
    ax.axis("off")
    ax.text(0.5, 0.5, text, ha="center", va="center", color=theme.MUTED, fontsize=11, wrap=True)


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
            color = theme.STATUS["critical"] if in_flight else theme.MUTED
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
                          fontsize=10, fontweight="bold", color=theme.STATUS["critical"])
    return True


def build_summary(log: LogData, flags):
    fig = Figure()
    fig.suptitle("Flight Log Summary", fontsize=15, fontweight="bold", color=theme.INK, x=0.03, ha="left")
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
        ax.text(0, y, line, fontsize=11, color=theme.INK, transform=ax.transAxes, va="top")
        y -= 0.065

    y -= 0.03
    ax.text(0, y, "Automatic checks", fontsize=12, fontweight="bold", color=theme.INK, transform=ax.transAxes, va="top")
    y -= 0.07
    for sev, text in flags:
        color = theme.STATUS.get(sev, theme.INK2)
        marker = {"good": "OK", "warning": "!", "serious": "!!", "critical": "!!!"}.get(sev, "-")
        ax.text(0, y, marker, fontsize=11, fontweight="bold", color=color, transform=ax.transAxes, va="top")
        ax.text(0.06, y, text, fontsize=10.5, color=theme.INK, transform=ax.transAxes, va="top", wrap=True)
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
        color = theme.LINE_CATEGORICAL[y_of[name] % len(theme.LINE_CATEGORICAL)]
        ax.barh(y_of[name], e - s, left=s, height=0.6, color=color, edgecolor="none")

    if fs_intervals:
        fs_row = len(names)
        for s, e in fs_intervals:
            ax.barh(fs_row, e - s, left=s, height=0.6, color=theme.STATUS["critical"], edgecolor="none")
        names = names + [fs_row_name]

    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names)
    for tick_label, name in zip(ax.get_yticklabels(), names):
        if name == fs_row_name:
            tick_label.set_color(theme.STATUS["critical"])
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
        cell.set_edgecolor(theme.GRID)
        if r == 0:
            cell.set_facecolor("#efeeea")
            cell.set_text_props(fontweight="bold", color=theme.INK)
        else:
            cell.set_facecolor(theme.SURFACE)
    if len(rows) > 40:
        fig.text(0.02, 0.01, f"... and {len(rows) - 40} more (see PDF export for the full list)",
                  fontsize=8, color=theme.MUTED)
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
            cell.set_edgecolor(theme.GRID)
            cell.set_facecolor("#efeeea" if r == 0 else theme.SURFACE)
            if r == 0:
                cell.set_text_props(fontweight="bold", color=theme.INK)
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
            ("POS", "RelHomeAlt", "Rel. altitude (POS)", theme.HUE["blue"]),
            ("BARO", "Alt", "Barometric altitude", theme.HUE["aqua"]),
        ], "meters"),
        ("Airspeed", [
            ("ARSP", "Airspeed", "Airspeed (sensor)", theme.HUE["violet"]),
            ("CTUN", "As", "Airspeed (control loop)", theme.HUE["orange"]),
        ], "m/s"),
        ("Climb / groundspeed", [
            ("GPS", "Spd", "Ground speed", theme.HUE["green"]),
            ("GPS", "VZ", "Vertical speed", theme.HUE["red"]),
        ], "m/s"),
    ]
    fig = _stack_plot(log, specs)
    if fig is None:
        return None
    return "Altitude & Airspeed", fig


def build_attitude(log: LogData):
    specs = [
        ("Roll", [("ATT", "Roll", "Actual", theme.HUE["blue"]), ("ATT", "DesRoll", "Desired", theme.HUE["orange"])], "deg"),
        ("Pitch", [("ATT", "Pitch", "Actual", theme.HUE["blue"]), ("ATT", "DesPitch", "Desired", theme.HUE["orange"])], "deg"),
        ("Yaw / heading", [("ATT", "Yaw", "Actual", theme.HUE["blue"]), ("ATT", "DesYaw", "Desired", theme.HUE["orange"])], "deg"),
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
            series.append((mt, col, label, theme.HUE[hue]))
        specs.append((f"{axis} rate controller", series, ""))
    fig = _stack_plot(log, specs)
    if fig is None:
        return None
    return "PID Tuning", fig


def build_battery(log: LogData):
    specs = [
        ("Voltage", [("BAT", "Volt", "Battery voltage", theme.HUE["blue"]), ("BAT", "VoltR", "Sag-resistant estimate", theme.HUE["aqua"])], "V"),
        ("Current", [("BAT", "Curr", "Current draw", theme.HUE["red"])], "A"),
        ("Remaining capacity", [("BAT", "RemPct", "Remaining", theme.HUE["green"])], "%"),
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
                ax1.plot(log.t("RCIN"), log.col("RCIN", c), lw=1, color=theme.LINE_CATEGORICAL[i - 1], label=f"RC{i} in")
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
                ax2.plot(log.t("RCOU"), log.col("RCOU", c), lw=1, color=theme.LINE_CATEGORICAL[(i - 1) % len(theme.LINE_CATEGORICAL)], label=f"Servo {i}")
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
        ax1.plot(log.t("RSSI"), log.col("RSSI", "RXLQ"), lw=1.1, color=theme.HUE["aqua"], label="Link quality (%)")
        plotted = True
    if log.has("RSSI", "RXRSSI"):
        rssi = np.asarray(log.col("RSSI", "RXRSSI"), dtype=float)
        rssi_pct = rssi * 100.0 if np.nanmax(rssi) <= 1.0 else rssi
        ax1.plot(log.t("RSSI"), rssi_pct, lw=1.1, color=theme.HUE["blue"], label="RSSI (scaled)")
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
                ax2.plot(log.t("RCIN"), log.col("RCIN", c), lw=1, color=theme.LINE_CATEGORICAL[i - 1], label=f"RC{i} in")
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
                  fontsize=7.5, color=theme.MUTED)
    return "RC Link (ELRS)", fig


def build_vibration(log: LogData):
    if not log.has("VIBE"):
        return None
    fig = Figure()
    axes = fig.subplots(2, 1, sharex=True)
    ax = axes[0]
    for axis, hue in (("VibeX", "blue"), ("VibeY", "aqua"), ("VibeZ", "violet")):
        if log.has("VIBE", axis):
            ax.plot(log.t("VIBE"), log.col("VIBE", axis), lw=0.8, color=theme.HUE[hue], label=axis)
    ax.axhline(VIBE_WARN, color=theme.STATUS["warning"], ls="--", lw=1, label="Warning level")
    ax.axhline(VIBE_CRIT, color=theme.STATUS["critical"], ls="--", lw=1, label="Critical level")
    ax.set_title("Vibration levels", loc="left", fontsize=10)
    ax.set_ylabel("m/s/s")
    ax.legend(loc="upper right", fontsize=8, ncol=2, frameon=False)

    ax2 = axes[1]
    if log.has("VIBE", "Clip"):
        ax2.plot(log.t("VIBE"), log.col("VIBE", "Clip"), lw=1, color=theme.HUE["red"])
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
        ("Main loop load", [("PM", "Load", "Load", theme.HUE["blue"])], "%"),
        ("Link quality", [("RSSI", "RXLQ", "Link quality", theme.HUE["aqua"]), ("RSSI", "RXRSSI", "RSSI", theme.HUE["orange"])], ""),
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
    ax.plot(lng, lat, lw=1.2, color=theme.HUE["blue"])
    ax.scatter([lng[0]], [lat[0]], color=theme.STATUS["good"], zorder=5, label="Start")
    ax.scatter([lng[-1]], [lat[-1]], color=theme.STATUS["critical"], zorder=5, label="End")
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
