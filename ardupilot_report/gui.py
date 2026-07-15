"""The PySide6 GUI: ReportApp main window and the CLI entry point."""

import os
import sys
import glob
import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QToolBar, QPushButton,
    QCheckBox, QComboBox, QLabel, QSpinBox, QTabWidget, QFileDialog,
    QMessageBox,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.backends.backend_pdf import PdfPages

from . import theme
from .logdata import LogData, fmt_seconds
from .figures import build_report, events_pdf_pages
from .discovery import find_sd_logs_dir, discover_logs_in_dir, _log_number, MERGED_LABEL, _resolve_cli_path


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
        bar.setObjectName("mainToolbar")
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
        self.accent_choice.addItems(list(theme.ACCENT_THEMES.keys()))
        self.accent_choice.currentTextChanged.connect(self.on_accent_changed)
        bar.addWidget(self.accent_choice)

        bar.addWidget(QLabel("Font:"))
        self.font_choice = QComboBox()
        self.font_choice.addItems(list(theme.FONT_FAMILIES.keys()))
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
        accent = theme.ACCENT_THEMES[self.accent][self.mode]
        self.setStyleSheet(theme.build_stylesheet(self.mode, accent))

    def _apply_font(self):
        family, style_hint = theme.FONT_FAMILIES[self.font_family]
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
        theme.apply_chart_theme(self.mode, self.font_family, self.font_size)
        self._apply_stylesheet()
        self._rebuild_pages()

    def on_accent_changed(self, text):
        self.accent = text
        self._apply_stylesheet()

    def on_font_changed(self, text):
        self.font_family = text
        theme.apply_chart_theme(self.mode, self.font_family, self.font_size)
        self._apply_font()
        self._rebuild_pages()

    def on_font_size_changed(self, value):
        self.font_size = value
        theme.apply_chart_theme(self.mode, self.font_family, self.font_size)
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


def main():
    initial = _resolve_cli_path(sys.argv)
    app = QApplication(sys.argv)
    window = ReportApp(initial_path=initial)
    window.show()
    sys.exit(app.exec())
