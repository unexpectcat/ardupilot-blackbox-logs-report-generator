"""Palette / theming (validated categorical/status palette - see dataviz
color-formula & palette.md). Chart colors (categorical hues + status) are
frozen per light/dark mode - a surface adopts one theme and never mixes -
so only light/dark switches them. The "color scheme" picker only changes
the surrounding Qt chrome's accent color; it never touches chart data color.
"""

from PySide6.QtGui import QFont

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt

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
              "muted": "#898781", "border": "rgba(11,11,11,0.14)", "border_faint": "rgba(11,11,11,0.08)"},
    "dark": {"page": "#0d0d0d", "panel": "#1a1a19", "ink": "#ffffff", "ink2": "#c3c2b7",
             "muted": "#898781", "border": "rgba(255,255,255,0.14)", "border_faint": "rgba(255,255,255,0.08)"},
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

# Mutable "current" chart theme state - figures.py reads these module globals
# (via `theme.HUE` etc., never a `from .theme import HUE`) so re-assigning them
# here and calling apply_chart_theme() again is enough to re-theme every figure
# built after.
HUE = dict(CHART_THEMES["light"]["hue"])
LINE_CATEGORICAL = [HUE[k] for k in CATEGORICAL_ORDER]
INK = INK2 = MUTED = GRID = SURFACE = None


def apply_chart_theme(mode, font_family="Sans Serif", font_size=9):
    """Re-point the module-level chart color/font globals at `mode` ("light"/"dark")
    and push them into matplotlib's rcParams. Figures built after this call pick
    up the new theme; already-built Figure objects do not change retroactively."""
    global HUE, LINE_CATEGORICAL, INK, INK2, MUTED, GRID, SURFACE
    chart = CHART_THEMES[mode]
    HUE = dict(chart["hue"])
    LINE_CATEGORICAL = [HUE[k] for k in CATEGORICAL_ORDER]
    INK, INK2, MUTED, GRID, SURFACE = chart["ink"], chart["ink2"], chart["muted"], chart["grid"], chart["surface"]

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


def _hex_to_rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _blend(hex_a, hex_b, t):
    """Blend hex_a toward hex_b by fraction t (0 = hex_a, 1 = hex_b)."""
    ra, ga, ba = _hex_to_rgb(hex_a)
    rb, gb, bb = _hex_to_rgb(hex_b)
    r = round(ra + (rb - ra) * t)
    g = round(ga + (gb - ga) * t)
    b = round(ba + (bb - ba) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def build_stylesheet(mode, accent):
    """Qt stylesheet for the app chrome. Chart colors are untouched by this -
    only window/toolbar/tab/button/checkbox colors follow `mode` and `accent`."""
    c = CHROME_THEMES[mode]
    # Tint the toolbar toward the accent so it reads as a distinct band from the
    # tab content below, and so the "color scheme" choice is visible even with
    # no log loaded. Blended (not translucent) so it stays a flat, predictable
    # color regardless of what's underneath.
    tint_t = 0.22 if mode == "light" else 0.30
    toolbar_bg = _blend(c["panel"], accent, tint_t)
    # A soft, neutral (not accent-colored) wash for hover states - blend the
    # panel toward black on light surfaces / toward white on dark ones.
    hover_bg = _blend(c["panel"], "#000000" if mode == "light" else "#ffffff", 0.08)
    return f"""
    QMainWindow, QWidget {{ background: {c['page']}; color: {c['ink']}; }}
    QToolBar {{ background: {c['panel']}; border: none; border-bottom: 1px solid {c['border']};
                spacing: 8px; padding: 6px; }}
    QToolBar#mainToolbar {{ background: {toolbar_bg}; border-bottom: 2px solid {accent}; }}
    QToolBar QLabel {{ color: {c['ink2']}; padding: 0 2px; background: transparent; }}
    QPushButton {{ background: transparent; color: {c['ink']}; border: 1px solid transparent;
                   border-radius: 6px; padding: 6px 14px; }}
    QPushButton:hover {{ background: {hover_bg}; border: 1px solid {c['border_faint']}; }}
    QPushButton:pressed {{ background: {accent}; color: white; border: 1px solid {accent}; }}
    QPushButton#stepBtn {{ padding: 4px 10px; font-weight: 600; }}
    QComboBox, QSpinBox {{ background: transparent; color: {c['ink']}; border: 1px solid transparent;
                            padding: 4px 8px; min-height: 18px; }}
    QSpinBox {{ border-radius: 6px; }}
    QComboBox {{
        border-top-left-radius: 6px; border-bottom-left-radius: 6px;
        border-top-right-radius: 0; border-bottom-right-radius: 0;
    }}
    QComboBox:hover, QSpinBox:hover {{ background: {hover_bg}; border: 1px solid {c['border_faint']}; }}
    QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['ink']}; selection-background-color: {accent};
                                    selection-color: white; outline: none; }}
    QCheckBox {{ color: {c['ink']}; spacing: 6px; background: transparent; }}
    QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {c['border']}; border-radius: 3px;
                             background: {c['panel']}; }}
    QCheckBox::indicator:checked {{ background: {accent}; border: 1px solid {accent}; }}
    QCheckBox::indicator:hover {{ background: {hover_bg}; }}
    QLabel {{ color: {c['ink2']}; background: transparent; }}
    QLabel#status {{ color: {c['ink2']}; padding-left: 8px; }}
    QTabWidget::pane {{ border-top: 1px solid {c['border']}; background: {c['panel']}; }}
    QTabBar::tab {{ background: transparent; color: {c['ink2']}; padding: 8px 18px;
                    border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {c['ink']}; border-bottom: 2px solid {accent}; font-weight: 600; }}
    QTabBar::tab:hover {{ color: {c['ink']}; }}
    """


apply_chart_theme("light")  # establish rcParams defaults before any Figure is built
