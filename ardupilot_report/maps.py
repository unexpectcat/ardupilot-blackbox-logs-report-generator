"""OpenStreetMap tile fetching for the Summary map background.

Network calls are strictly best-effort: any failure (offline, DNS, blocked,
slow server) is caught and reported as `None`, so callers always have a
theme-colored flat background to fall back to - the trajectory/dots never
depend on a tile fetch succeeding.

Tiles are cached in-process for the life of the app, keyed by (zoom, x, y),
so switching Light/Dark/font/accent (which rebuilds every figure) never
re-hits the tile server for a log that's already been mapped once.
"""

import io
import math
import urllib.request
import urllib.error

import numpy as np
import matplotlib.image as mpimg

TILE_SIZE = 256
USER_AGENT = "ardupilot_log_report/1.0 (desktop flight-log viewer; contact via GitHub issues)"
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

_TILE_CACHE = {}  # (z, x, y) -> np.ndarray


def project(lon, lat, zoom):
    """Web-Mercator lon/lat -> absolute pixel coordinates at `zoom`.

    Scalar or numpy-array input. Shared by both the tile-bbox picker and the
    trajectory plotter so the two are always pixel-aligned.
    """
    lat = np.clip(lat, -85.05112878, 85.05112878)
    lat_rad = np.radians(lat)
    n = 2.0 ** zoom
    x = (np.asarray(lon, dtype=float) + 180.0) / 360.0 * n * TILE_SIZE
    y = (1.0 - np.log(np.tan(lat_rad) + 1.0 / np.cos(lat_rad)) / np.pi) / 2.0 * n * TILE_SIZE
    return x, y


def _tile_bounds(lat_min, lat_max, lon_min, lon_max, zoom):
    x0px, y0px = project(lon_min, lat_max, zoom)
    x1px, y1px = project(lon_max, lat_min, zoom)
    x0 = int(math.floor(x0px / TILE_SIZE))
    x1 = int(math.floor(x1px / TILE_SIZE))
    y0 = int(math.floor(y0px / TILE_SIZE))
    y1 = int(math.floor(y1px / TILE_SIZE))
    return x0, x1, y0, y1


def _choose_zoom(lat_min, lat_max, lon_min, lon_max, max_tiles=36, max_zoom=18):
    for zoom in range(max_zoom, -1, -1):
        x0, x1, y0, y1 = _tile_bounds(lat_min, lat_max, lon_min, lon_max, zoom)
        n_tiles = (x1 - x0 + 1) * (y1 - y0 + 1)
        if n_tiles <= max_tiles:
            return zoom, (x0, x1, y0, y1)
    return 0, _tile_bounds(lat_min, lat_max, lon_min, lon_max, 0)


def _fetch_tile(z, x, y, timeout):
    n = 2 ** z
    key = (z, x % n, y)
    if key in _TILE_CACHE:
        return _TILE_CACHE[key]
    if y < 0 or y >= n:
        img = np.ones((TILE_SIZE, TILE_SIZE, 3), dtype=np.float32)  # off-world (poles) - blank white
        _TILE_CACHE[key] = img
        return img
    url = TILE_URL.format(z=z, x=x % n, y=y)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    img = mpimg.imread(io.BytesIO(data), format="png")
    _TILE_CACHE[key] = img
    return img


class Basemap:
    """A stitched tile image plus its Web-Mercator origin/zoom, so callers can
    project their own lon/lat points into the same pixel space via `project()`."""

    def __init__(self, image, zoom, x0, y0):
        self.image = image
        self.zoom = zoom
        self.x0 = x0
        self.y0 = y0
        self.height, self.width = image.shape[0], image.shape[1]

    def project(self, lon, lat):
        px, py = project(lon, lat, self.zoom)
        return px - self.x0 * TILE_SIZE, py - self.y0 * TILE_SIZE


def fetch_basemap(lat_min, lat_max, lon_min, lon_max, pad_frac=0.20, min_pad_deg=0.0015,
                   max_tiles=36, timeout=3.0):
    """Best-effort OSM basemap for a bounding box. Returns a `Basemap`, or
    `None` on any failure (offline, blocked, timeout, ...)."""
    try:
        lat_span = max(lat_max - lat_min, min_pad_deg)
        lon_span = max(lon_max - lon_min, min_pad_deg)
        lat_pad = max(lat_span * pad_frac, min_pad_deg)
        lon_pad = max(lon_span * pad_frac, min_pad_deg)
        lat_min, lat_max = lat_min - lat_pad, lat_max + lat_pad
        lon_min, lon_max = lon_min - lon_pad, lon_max + lon_pad

        zoom, (x0, x1, y0, y1) = _choose_zoom(lat_min, lat_max, lon_min, lon_max, max_tiles=max_tiles)
        cols, rows = x1 - x0 + 1, y1 - y0 + 1

        first = _fetch_tile(zoom, x0, y0, timeout)
        channels = first.shape[2]
        composite = np.ones((rows * TILE_SIZE, cols * TILE_SIZE, channels), dtype=first.dtype)
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                tile = first if (tx, ty) == (x0, y0) else _fetch_tile(zoom, tx, ty, timeout)
                if tile.shape[2] != channels:
                    tile = tile[:, :, :channels] if tile.shape[2] > channels else np.dstack(
                        [tile] + [np.ones_like(tile[:, :, :1])] * (channels - tile.shape[2]))
                r, c = ty - y0, tx - x0
                composite[r * TILE_SIZE:(r + 1) * TILE_SIZE, c * TILE_SIZE:(c + 1) * TILE_SIZE, :] = tile

        return Basemap(composite, zoom, x0, y0)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return None
