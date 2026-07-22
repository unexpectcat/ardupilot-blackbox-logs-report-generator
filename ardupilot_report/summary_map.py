"""Summary tab's map: OSM basemap + mode-colored flight trajectory + dots for
timestamped automatic-check flags, each with an offset label and a dotted
leader line back to its dot.

`build_map_figure()` returns the Figure plus a `category -> [artists]` dict so
gui.py's sidebar checkboxes can toggle a whole category's dots/labels on or
off in-place (`artist.set_visible()` + `canvas.draw_idle()`), no figure
rebuild needed.
"""

import textwrap

import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from . import theme
from . import maps
from .analysis import mode_intervals, timestamped_categories
from .figures import mode_color_map, _blank_axis_message


def _position_source(log):
    """(times, y, x, kind) for whatever position data the log has, or None.

    kind == "geo": y/x are lat/lng (WGS84 degrees) - real basemap tiles apply.
    kind == "local": y/x are North/East in meters from the EKF origin - there
    is no GPS at all, so there's nothing to put a basemap under; the caller
    just draws the raw coordinate line.
    """
    if log.has("GPS", "Lat") and log.nonzero("GPS", "Lat"):
        return log.t("GPS"), log.col("GPS", "Lat"), log.col("GPS", "Lng"), "geo"
    if log.has("POS", "Lat") and log.nonzero("POS", "Lat"):
        return log.t("POS"), log.col("POS", "Lat"), log.col("POS", "Lng"), "geo"
    for mt in ("XKF1", "NKF1"):
        if log.has(mt, "PN") and log.has(mt, "PE") and log.nonzero(mt, "PN"):
            return log.t(mt), log.col(mt, "PN"), log.col(mt, "PE"), "local"
    return None


def _nearest_index(times, t):
    idx = int(np.searchsorted(times, t))
    if idx <= 0:
        return 0
    if idx >= len(times):
        return len(times) - 1
    return idx if abs(times[idx] - t) < abs(times[idx - 1] - t) else idx - 1


def _place_labels(instances, cx, span_y, pixel_space):
    """Greedy vertical decluttering: split instances left/right of the map's
    horizontal center, stack each side's labels top-to-bottom with a minimum
    gap, offsetting each label away from the map on its side."""
    if not instances:
        return []
    dx = max(span_y * (0.16 if pixel_space else 0.30), 24 if pixel_space else span_y * 0.2 or 1)
    min_gap = max(span_y * 0.11, 46 if pixel_space else span_y * 0.11)
    # In pixel space y grows downward (top of image = 0); in plain data space
    # (no basemap) y grows upward. Sort/stack "top of the view first" either way.
    key = (lambda it: it[3]) if pixel_space else (lambda it: -it[3])

    placed = []
    for items, sign, ha in (
        (sorted([it for it in instances if it[2] < cx], key=key), -1, "right"),
        (sorted([it for it in instances if it[2] >= cx], key=key), 1, "left"),
    ):
        last_y = None
        for cat, flag, x, y in items:
            if last_y is None:
                ly = y
            else:
                ly = max(y, last_y + min_gap) if pixel_space else min(y, last_y - min_gap)
            last_y = ly
            placed.append((cat, flag, x, y, x + sign * dx, ly, ha))
    return placed


def build_map_figure(log, flags, active_categories=None):
    """Returns (Figure, {category: [artists]})."""
    fig = Figure()
    groups = timestamped_categories(flags)
    active = set(groups) if active_categories is None else set(active_categories)

    src = _position_source(log)
    if src is None:
        ax = fig.add_axes((0.06, 0.06, 0.88, 0.88))
        _blank_axis_message(ax, "No position data (GPS or local EKF estimate) was recorded in this log.")
        return fig, {}

    times, lat, lng, kind = src
    times = np.asarray(times, dtype=float)
    lat = np.asarray(lat, dtype=float)
    lng = np.asarray(lng, dtype=float)
    finite = np.isfinite(times) & np.isfinite(lat) & np.isfinite(lng)
    times, lat, lng = times[finite], lat[finite], lng[finite]
    if len(lat) < 2:
        ax = fig.add_axes((0.06, 0.06, 0.88, 0.88))
        _blank_axis_message(ax, "Not enough position samples to draw a trajectory.")
        return fig, {}

    basemap = None
    if kind == "geo":
        basemap = maps.fetch_basemap(float(np.min(lat)), float(np.max(lat)), float(np.min(lng)), float(np.max(lng)))

    ax = fig.add_axes((0.05, 0.05, 0.9, 0.88))
    ax.set_facecolor(theme.SURFACE)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_aspect("equal", adjustable="datalim")

    if basemap is not None:
        ax.imshow(basemap.image, extent=(0, basemap.width, basemap.height, 0),
                   interpolation="bilinear", zorder=0)
        px, py = basemap.project(lng, lat)
        pixel_space = True
        ax.set_title("Flight trajectory - OpenStreetMap", loc="left", fontsize=10, color=theme.INK)
    else:
        px, py = lng, lat
        pixel_space = False
        if kind == "geo":
            ax.set_title("Flight trajectory - map unavailable (offline?)", loc="left", fontsize=10, color=theme.INK)
        else:
            ax.set_title("Local position - no GPS installed (EKF-relative, meters)",
                          loc="left", fontsize=10, color=theme.INK)

    colors = mode_color_map(log)
    intervals = mode_intervals(log)
    if intervals:
        for name, s, e in intervals:
            mask = (times >= s) & (times <= e)
            if np.count_nonzero(mask) >= 2:
                ax.plot(px[mask], py[mask], color=colors[name], lw=2.2, solid_capstyle="round", zorder=2)
        handles = [Line2D([0], [0], color=colors[n], lw=2.5) for n in sorted(colors)]
        ax.legend(handles, sorted(colors), loc="lower right", fontsize=7.5,
                   frameon=basemap is not None, framealpha=0.85, facecolor=theme.SURFACE, labelcolor=theme.INK)
    else:
        ax.plot(px, py, color=theme.HUE["blue"], lw=2.2, zorder=2)

    # Diamond markers (vs. the round flag dots below) so a start/end point
    # sharing a severity color (e.g. "good"/"critical") never reads as a flag.
    ax.scatter([px[0]], [py[0]], color=theme.STATUS["good"], marker="D", zorder=5, s=42,
               edgecolor=theme.SURFACE, linewidths=1.0, label="Start")
    ax.scatter([px[-1]], [py[-1]], color=theme.STATUS["critical"], marker="D", zorder=5, s=42,
               edgecolor=theme.SURFACE, linewidths=1.0, label="End")

    category_artists = {}
    instances = []
    for cat, fl_list in groups.items():
        for f in fl_list:
            idx = _nearest_index(times, f.t)
            instances.append((cat, f, float(px[idx]), float(py[idx])))

    if instances:
        cx = (basemap.width / 2.0) if basemap is not None else float(np.mean(px))
        span_y = float(basemap.height) if basemap is not None else (float(np.ptp(py)) or 1.0)
        for cat, f, x, y, lx, ly, ha in _place_labels(instances, cx, span_y, pixel_space):
            visible = cat in active
            color = theme.STATUS.get(f.severity, theme.INK2)
            dot = ax.scatter([x], [y], color=color, s=46, zorder=6, edgecolor=theme.SURFACE, linewidths=1.0)
            leader = ax.plot([x, lx], [y, ly], color=theme.MUTED, lw=0.9, ls=":", zorder=5)[0]
            label = ax.annotate(textwrap.fill(f.text, width=28), xy=(lx, ly), xycoords="data",
                                  ha=ha, va="center", fontsize=7.3, color=theme.INK, zorder=7,
                                  bbox=dict(boxstyle="round,pad=0.28", fc=theme.SURFACE, ec=color, lw=0.8, alpha=0.92))
            for artist in (dot, leader, label):
                artist.set_visible(visible)
            category_artists.setdefault(cat, []).extend([dot, leader, label])
        ax.margins(x=0.22, y=0.16)

    return fig, category_artists
