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
# "Slate" is the neutral/no-hue option - a plain gray, for anyone who wants the
# accent stripes without a color statement.
ACCENT_THEMES = {
    "Ocean": {"light": "#2a78d6", "dark": "#3987e5"},
    "Ember": {"light": "#eb6834", "dark": "#d95926"},
    "Amethyst": {"light": "#4a3aa7", "dark": "#9085e9"},
    "Slate": {"light": "#5f5e59", "dark": "#a6a49b"},
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


def build_stylesheet(mode, accent):
    """Qt stylesheet for the app chrome. Chart colors are untouched by this -
    only window/toolbar/tab/button/checkbox colors follow `mode` and `accent`."""
    c = CHROME_THEMES[mode]
    # No background tint on the toolbar - the accent instead shows as two plain
    # 7px lines: one under the toolbar, one down the side of the report viewport.
    # A flat, real-alpha black wash for hover states (not accent-colored),
    # consistent in both modes since black-over-anything just darkens it a touch.
    hover_bg = "rgba(0, 0, 0, 0.05)"
    return f"""
    QMainWindow, QWidget {{ background: {c['page']}; color: {c['ink']}; }}
    QToolBar {{ background: {c['panel']}; border: none; border-bottom: 1px solid {c['border']};
                spacing: 8px; padding: 6px; }}
    QToolBar#mainToolbar {{ border-bottom: 7px solid {accent}; }}
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
    QTabWidget::pane {{ border-top: 1px solid {c['border']}; border-left: 7px solid {accent};
                         background: {c['panel']}; }}
    QTabBar::tab {{ background: transparent; color: {c['ink2']}; padding: 8px 18px;
                    border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {c['ink']}; border-bottom: 2px solid {accent}; font-weight: 600; }}
    QTabBar::tab:hover {{ color: {c['ink']}; }}
    """


apply_chart_theme("light")  # establish rcParams defaults before any Figure is built
