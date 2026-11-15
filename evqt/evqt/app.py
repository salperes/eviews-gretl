"""EViews-style main window on top of gretl (GretlEngine)."""
from __future__ import annotations

import os
import re
import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import (QAction, QColor, QPalette, QFont, QFontDatabase, QIcon, QKeySequence,
                           QPainter, QPen, QPixmap, QTextCursor)
from PySide6.QtWidgets import (QApplication, QComboBox, QSizePolicy, QDialog, QDialogButtonBox,
                               QDockWidget, QFileDialog, QFormLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMainWindow, QMdiArea, QMenu, QMessageBox,
                               QPlainTextEdit, QScrollArea, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from .engine import GretlEngine, GretlError

import evprg2hansl as tr  # noqa: E402

MONO = QFont("Menlo")
MONO.setStyleHint(QFont.Monospace)
MONO.setFixedPitch(True)
MONO.setPointSize(12)


# ---------------------------------------------------------------------------
# Small drawn icons for workfile objects
# ---------------------------------------------------------------------------

def _icon(kind: str) -> QIcon:
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    colors = {"series": "#2e7d32", "equation": "#1565c0", "group": "#6a1b9a",
              "scalar": "#ef6c00", "string": "#5d4037", "bundle": "#455a64", "workfile": "#00838f"}
    c = QColor(colors.get(kind, "#455a64"))
    p.setPen(QPen(c.darker(130), 1))
    p.setBrush(c.lighter(185))
    p.drawRoundedRect(1, 1, 16, 16, 3, 3)
    p.setPen(QPen(c.darker(120), 1.6))
    if kind == "series":
        p.drawPolyline([(QPixmapPoint(x, y)) for x, y in ((4, 12), (7, 7), (10, 10), (14, 4))])
    else:
        glyph = {"equation": "=", "group": "G", "scalar": "#", "string": "a", "bundle": "b",
                 "workfile": "W"}.get(kind, "?")
        f = QFont()
        f.setBold(True)
        f.setPixelSize(12)
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignCenter, glyph)
    p.end()
    return QIcon(pm)


def QPixmapPoint(x, y):
    from PySide6.QtCore import QPointF
    return QPointF(x, y)


class ScaledImage(QLabel):
    """Shows a graph scaled to the window, keeping its aspect ratio."""

    def __init__(self):
        super().__init__(alignment=Qt.AlignCenter)
        self._orig = QPixmap()
        self.setMinimumSize(80, 60)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

    def set_image(self, pm: QPixmap):
        self._orig = pm
        self._rescale()

    def original(self) -> QPixmap:
        return self._orig

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def _rescale(self):
        if not self._orig.isNull():
            self.setPixmap(self._orig.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


def _toolbar(buttons: list[tuple[str, object]]) -> QWidget:
    """A row of flat text buttons, like an EViews object window toolbar.

    Each entry is (label, callback) or (label, [(item, callback), ...]) for a menu.
    """
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(2, 2, 2, 2)
    lay.setSpacing(1)
    for label, action in buttons:
        if label == "|":
            sep = QLabel(" ")
            lay.addWidget(sep)
            continue
        b = QToolButton()
        b.setText(label)
        b.setAutoRaise(False)
        b.setObjectName("objbtn")
        b.setToolButtonStyle(Qt.ToolButtonTextOnly)
        b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        if isinstance(action, list):
            m = QMenu(b)
            for item, cb in action:
                if item == "-":
                    m.addSeparator()
                else:
                    m.addAction(item, cb)
            b.setMenu(m)
            b.setPopupMode(QToolButton.InstantPopup)
        elif action is None:
            b.setEnabled(False)
        else:
            b.clicked.connect(action)
        lay.addWidget(b)
    lay.addStretch(1)
    w.setObjectName("objbar")
    sc = QScrollArea()
    sc.setWidget(w)
    sc.setWidgetResizable(True)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sc.setFrameShape(QScrollArea.NoFrame)
    sc.setFixedHeight(w.sizeHint().height())
    sc.setObjectName("objbar")
    return sc


# ---------------------------------------------------------------------------
# Object windows
# ---------------------------------------------------------------------------

class ObjectWindow(QWidget):
    """Base: toolbar on top, stacked views below."""

    def __init__(self, main: "MainWindow", title: str):
        super().__init__()
        self.main = main
        self.setWindowTitle(title)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.stack = QStackedWidget()
        self.text = QPlainTextEdit(readOnly=True)
        self.text.setFont(MONO)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.table = QTableWidget()
        self.image = ScaledImage()
        self.image.setStyleSheet("background: white;")
        for w in (self.text, self.table, self.image):
            self.stack.addWidget(w)
        self._scroll = self.image

    def set_toolbar(self, bar: QWidget):
        self.lay.addWidget(bar)
        self.lay.addWidget(self.stack, 1)

    def show_text(self, text: str):
        self.text.setPlainText(text)
        self.stack.setCurrentWidget(self.text)

    def show_lines(self, lines: list[str]):
        self.show_text("\n".join(lines).strip("\n"))

    def show_image(self, path: str):
        self.image.set_image(QPixmap(path))
        self.stack.setCurrentWidget(self._scroll)

    def show_table(self, header: list[str], rows: list[list[str]]):
        t = self.table
        t.clear()
        t.setColumnCount(len(header) - 1)
        t.setRowCount(len(rows))
        t.setHorizontalHeaderLabels(header[1:])
        t.setVerticalHeaderLabels([r[0] for r in rows])
        for i, r in enumerate(rows):
            for j, v in enumerate(r[1:]):
                it = QTableWidgetItem(v if v not in ("", "NA") else "NA")
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(i, j, it)
        t.resizeColumnsToContents()
        self.stack.setCurrentWidget(t)

    def run_text(self, cmd: str):
        try:
            self.show_lines(self.main.engine.run(cmd, check=True))
        except GretlError as e:
            self.main.error(str(e))

    def run_plot(self, cmd: str):
        try:
            self.show_image(self.main.engine.plot(cmd))
        except GretlError as e:
            self.main.error(str(e))

    def freeze(self):
        """Save what the window shows (EViews Freeze -> a file here)."""
        cur = self.stack.currentWidget()
        if cur is self._scroll:
            path, _ = QFileDialog.getSaveFileName(self, "Freeze graph", "", "PNG (*.png)")
            if path:
                self.image.original().save(path)
        elif cur is self.table:
            path, _ = QFileDialog.getSaveFileName(self, "Freeze table", "", "CSV (*.csv)")
            if path:
                with open(path, "w") as f:
                    t = self.table
                    f.write(",".join(["obs"] + [t.horizontalHeaderItem(j).text() for j in range(t.columnCount())]) + "\n")
                    for i in range(t.rowCount()):
                        f.write(",".join([t.verticalHeaderItem(i).text()] + [t.item(i, j).text() for j in range(t.columnCount())]) + "\n")
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Freeze output", "", "Text (*.txt)")
            if path:
                with open(path, "w") as f:
                    f.write(self.text.toPlainText())


class SeriesWindow(ObjectWindow):
    def __init__(self, main, name):
        super().__init__(main, f"Series: {name}   Workfile: {main.wf_title()}")
        self.name = name
        self.set_toolbar(_toolbar([
            ("View", [("Spreadsheet", self.spreadsheet),
                      ("Graph: Line", lambda: self.run_plot(f"gnuplot {name} --time-series --with-lines")),
                      ("Graph: Histogram", self.histogram),
                      ("-", None),
                      ("Descriptive Statistics", lambda: self.run_text(f"summary {name}\nnormtest {name} --jbera")),
                      ("Correlogram...", self.correlogram),
                      ("Unit Root Test (ADF)...", self.adf)]),
            ("Proc", [("Generate by Equation...", lambda: main.genr_dialog(f"{name} = ")),
                      ("Hodrick-Prescott Filter...", self.hpf)]),
            ("Object", [("Delete", lambda: main.delete_object(name))]),
            ("|", None),
            ("Name", lambda: main.rename_object(name)),
            ("Freeze", self.freeze),
            ("Sample", main.sample_dialog),
            ("Genr", lambda: main.genr_dialog()),
        ]))
        self.spreadsheet()

    def spreadsheet(self):
        try:
            h, rows = self.main.engine.series_values([self.name])
            self.show_table(h, rows)
        except GretlError as e:
            self.main.error(str(e))

    def histogram(self):
        path = self.main.engine.tmp_png()
        try:
            self.main.engine.run(f'freq {self.name} --normal --plot="{path}" --quiet', check=True)
            self.show_image(path)
        except GretlError as e:
            self.main.error(str(e))

    def correlogram(self):
        k, ok = QInputDialog.getInt(self, "Correlogram", "Lags to include:", 12, 1, 200)
        if ok:
            self.run_text(f"corrgm {self.name} {k} --quiet\ncorrgm {self.name} {k}")

    def adf(self):
        k, ok = QInputDialog.getInt(self, "Unit Root Test", "Maximum lags (AIC selection):", 8, 0, 60)
        if ok:
            self.run_text(f"adf {k} {self.name} --c --test-down=AIC")

    def hpf(self):
        lam, ok = QInputDialog.getDouble(self, "Hodrick-Prescott Filter", "Lambda (0 = default for frequency):", 0, 0, 1e9, 2)
        if ok:
            arg = f", {lam}" if lam > 0 else ""
            self.main.execute(f"series {self.name}_hp = {self.name} - hpfilt({self.name}{arg})", hansl=True)


class GroupWindow(ObjectWindow):
    def __init__(self, main, name):
        super().__init__(main, f"Group: {name}   Workfile: {main.wf_title()}")
        self.name = name
        self.set_toolbar(_toolbar([
            ("View", [("Spreadsheet", self.spreadsheet),
                      ("Graph: Line", lambda: self.run_plot(f"gnuplot {name} --time-series --with-lines")),
                      ("Graph: Scatter", self.scatter),
                      ("-", None),
                      ("Descriptive Stats", lambda: self.run_text(f"summary {name}")),
                      ("Covariance / Correlation", lambda: self.run_text(f"corr {name}"))]),
            ("Object", [("Delete", lambda: main.delete_object(name))]),
            ("|", None),
            ("Name", lambda: main.rename_object(name)),
            ("Freeze", self.freeze),
            ("Sample", main.sample_dialog),
        ]))
        self.spreadsheet()

    def members(self) -> list[str]:
        out = self.main.engine.run(f'printf "%s\\n", varname({self.name})')
        return [x for x in "".join(out).strip().split(",") if x]

    def spreadsheet(self):
        try:
            h, rows = self.main.engine.series_values([self.name])
            self.show_table(h, rows)
        except GretlError as e:
            self.main.error(str(e))

    def scatter(self):
        m = self.members()
        if len(m) >= 2:
            self.run_plot(f"gnuplot {' '.join(m[1:] + m[:1])} --fit=linear")


class EquationWindow(ObjectWindow):
    def __init__(self, main, name):
        super().__init__(main, f"Equation: {name.upper()}   Workfile: {main.wf_title()}")
        self.name = name
        self.set_toolbar(_toolbar([
            ("View", [("Estimation Output", self.output),
                      ("Actual, Fitted, Residual Graph", self.afr),
                      ("Residual Diagnostics", self.diag),
                      ("Coefficient Diagnostics: Wald Test...", self.wald)]),
            ("Proc", [("Make Residual Series...", lambda: self.make("resid")),
                      ("Make Fitted Series...", lambda: self.make("fit"))]),
            ("Object", [("Delete", lambda: main.delete_object(name))]),
            ("|", None),
            ("Name", lambda: main.rename_object(name)),
            ("Freeze", self.freeze),
            ("Estimate", self.estimate),
            ("Forecast", None),
            ("Stats", self.output),
            ("Resids", self.afr),
        ]))
        self.output()

    def output(self):
        try:
            self.show_text(self.main.engine.equation_text(self.name))
        except GretlError as e:
            self.main.error(str(e))

    def afr(self):
        try:
            self.main.engine.run(f"matrix ev_M = {self.name}.y ~ {self.name}.yhat ~ {self.name}.uhat\n"
                                 'cnameset(ev_M, defarray("Actual", "Fitted", "Residual"))', check=True)
            self.run_plot("gnuplot 1 2 3 --matrix=ev_M --time-series --with-lines --y2axis=3")
        except GretlError as e:
            self.main.error(str(e))

    def diag(self):
        self.run_text(f"ev_diag({self.name}, 2)")

    def wald(self):
        r, ok = QInputDialog.getText(self, "Wald Test", "Coefficient restrictions separated by commas,\ne.g. c(2)=0, c(3)=c(4):")
        if ok and r.strip():
            self.run_text(f'ev_wald({self.name}, "{r.strip()}")')

    def make(self, kind):
        default = f"resid{self.name[-2:]}" if kind == "resid" else f"{self.name}_fit"
        n, ok = QInputDialog.getText(self, "Make series", "Name for the new series:", text=default)
        if ok and n.strip():
            fn = "ev_resid" if kind == "resid" else "ev_fit"
            self.main.execute(f"series {n.strip()} = {fn}({self.name})", hansl=True)

    def estimate(self):
        spec = "".join(self.main.engine.run(f'printf "%s\\n", {self.name}.spec')).strip()
        self.main.equation_dialog(name=self.name, spec=spec, window=self)


# ---------------------------------------------------------------------------
# Workfile window
# ---------------------------------------------------------------------------

class WorkfileWindow(QWidget):
    def __init__(self, main: "MainWindow"):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(_toolbar([
            ("View", [("Spreadsheet of selected", self.open_selected_group),
                      ("Line graph of selected", self.graph_selected)]),
            ("Proc", [("Set Sample...", main.sample_dialog),
                      ("Generate Series...", main.genr_dialog)]),
            ("Object", [("Open Selected", self.open_selected),
                        ("Rename Selected...", self.rename_selected),
                        ("Delete Selected", self.delete_selected)]),
            ("|", None),
            ("Save", main.save_as),
            ("Freeze", None),
            ("Details+/-", self.toggle_details),
            ("Show", main.show_dialog),
            ("Fetch", None),
            ("Store", None),
            ("Delete", self.delete_selected),
            ("Genr", main.genr_dialog),
            ("Sample", main.sample_dialog),
        ]))
        info = QWidget()
        il = QVBoxLayout(info)
        il.setContentsMargins(6, 4, 6, 4)
        il.setSpacing(1)
        self.range_lbl = QLabel()
        self.sample_lbl = QLabel()
        for l in (self.range_lbl, self.sample_lbl):
            l.setFont(MONO)
            il.addWidget(l)
        info.setObjectName("wfinfo")
        lay.addWidget(info)
        self.list = QListWidget()
        self.list.setViewMode(QListView.ListMode)
        self.list.setFlow(QListView.TopToBottom)
        self.list.setWrapping(True)
        self.list.setResizeMode(QListView.Adjust)
        self.list.setGridSize(QSize(130, 22))
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda it: main.open_object(it.data(Qt.UserRole)))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
        lay.addWidget(self.list, 1)
        self.details = False
        self.tab_lbl = QLabel("  Untitled  /  New Page")
        self.tab_lbl.setObjectName("wftab")
        lay.addWidget(self.tab_lbl)

    def populate(self):
        wf = self.main.engine.wf
        self.range_lbl.setText(f"Range:  {wf.first} {wf.last}  --  {wf.nobs_full} obs")
        self.sample_lbl.setText(f"Sample: {wf.sample_first} {wf.sample_last}  --  {wf.sample_nobs} obs")
        self.list.clear()
        items = [(n, "series") for n in wf.series] + [(n, "group") for n in wf.lists] \
            + [(n, "equation") for n in wf.bundles] + [(n, "scalar") for n in wf.scalars] \
            + [(n, "string") for n in wf.strings]
        for name, kind in sorted(items, key=lambda x: x[0].lower()):
            label = name.lower()
            if self.details and kind == "scalar":
                label += f"   = {wf.scalars[name]}"
            elif self.details:
                label += f"   ({kind})"
            it = QListWidgetItem(_icon(kind), label)
            it.setData(Qt.UserRole, (name, kind))
            it.setToolTip(f"{kind}: {name}")
            self.list.addItem(it)
        self.tab_lbl.setText(f"  {os.path.basename(wf.path) if wf.path else 'Untitled'}  ")

    def toggle_details(self):
        self.details = not self.details
        self.list.setGridSize(QSize(260 if self.details else 130, 22))
        self.populate()

    def selected(self):
        return [it.data(Qt.UserRole) for it in self.list.selectedItems()]

    def open_selected(self):
        for obj in self.selected():
            self.main.open_object(obj)

    def open_selected_group(self):
        names = [n for n, k in self.selected() if k == "series"]
        if names:
            self.main.execute(f"group untitled {' '.join(names)}")
            self.main.open_object(("untitled", "group"))

    def graph_selected(self):
        names = [n for n, k in self.selected() if k == "series"]
        if names:
            self.main.graph_window(f"gnuplot {' '.join(names)} --time-series --with-lines", "Graph: " + " ".join(names))

    def rename_selected(self):
        for n, _ in self.selected()[:1]:
            self.main.rename_object(n)

    def delete_selected(self):
        names = [n for n, _ in self.selected()]
        if names and QMessageBox.question(self, "Delete", "Delete " + ", ".join(names) + "?") == QMessageBox.Yes:
            for n in names:
                self.main.delete_object(n, ask=False)

    def context_menu(self, pos):
        m = QMenu(self)
        m.addAction("Open", self.open_selected)
        m.addAction("Rename...", self.rename_selected)
        m.addAction("Delete", self.delete_selected)
        m.exec(self.list.mapToGlobal(pos))


# ---------------------------------------------------------------------------
# Command window
# ---------------------------------------------------------------------------

class CommandWindow(QPlainTextEdit):
    """Enter runs the line under the cursor (EViews-style)."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setFont(MONO)
        self.setPlaceholderText("Command window: type EViews commands (e.g.  ls dlog(GDP) c dlog(CONS)) and press Enter")

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            cur = self.textCursor()
            cur.select(QTextCursor.LineUnderCursor)
            line = cur.selectedText().strip()
            cur.movePosition(QTextCursor.EndOfLine)
            self.setTextCursor(cur)
            if cur.atEnd():
                super().keyPressEvent(e)
            else:
                self.moveCursor(QTextCursor.End)
                if self.toPlainText() and not self.toPlainText().endswith("\n"):
                    self.insertPlainText("\n")
            if line:
                self.main.execute(line)
            return
        super().keyPressEvent(e)


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------

def _form_dialog(parent, title: str, fields: list[tuple[str, QWidget]]) -> QDialog | None:
    d = QDialog(parent)
    d.setWindowTitle(title)
    f = QFormLayout(d)
    for label, w in fields:
        f.addRow(label, w)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    f.addRow(bb)
    return d if d.exec() == QDialog.Accepted else None


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, engine: GretlEngine | None = None):
        super().__init__()
        self.setWindowTitle("evqt — EViews-style interface for gretl")
        scr = QApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            self.resize(min(1500, int(g.width() * 0.92)), int(g.height() * 0.9))
        else:
            self.resize(1200, 800)
        self.engine = engine or GretlEngine()
        self.ctx = tr.Ctx()
        self.ctx.plot_files = True
        self.eq_count = 0
        self.windows: dict[str, QWidget] = {}

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.command = CommandWindow(self)
        self.command.setFixedHeight(110)
        cl.addWidget(self.command)
        self.mdi = QMdiArea()
        self.mdi.setBackground(QColor("#d9dde3"))
        cl.addWidget(self.mdi, 1)
        self.setCentralWidget(central)

        self.log = QPlainTextEdit(readOnly=True)
        self.log.setFont(MONO)
        self.log.setMaximumBlockCount(5000)
        dock = QDockWidget("Output", self)
        dock.setWidget(self.log)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.output_dock = dock

        self.wf_window = None
        self._menus()
        self.statusBar().showMessage("Path = " + os.path.expanduser("~") + "    WF = none")

    # -- menus ------------------------------------------------------------
    def _menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        f.addAction("New Workfile...", self.new_workfile)
        a = f.addAction("Open...", self.open_dialog)
        a.setShortcut(QKeySequence.Open)
        f.addAction("Save As (.gdt)...", self.save_as)
        f.addSeparator()
        f.addAction("Run Program (.prg)...", self.run_program_dialog)
        f.addSeparator()
        f.addAction("Exit", self.close)
        q = mb.addMenu("&Quick")
        q.addAction("Sample...", self.sample_dialog)
        q.addAction("Generate Series...", self.genr_dialog)
        q.addAction("Show...", self.show_dialog)
        q.addAction("Graph...", self.graph_dialog)
        q.addAction("Series Statistics...", self.stats_dialog)
        q.addSeparator()
        q.addAction("Estimate Equation...", lambda: self.equation_dialog())
        w = mb.addMenu("&Window")
        w.addAction("Cascade", self.mdi.cascadeSubWindows)
        w.addAction("Tile", self.mdi.tileSubWindows)
        w.addAction("Show Output Log", self.output_dock.show)
        h = mb.addMenu("&Help")
        h.addAction("About", lambda: QMessageBox.information(
            self, "About evqt",
            "evqt: an EViews-style interface for gretl.\n\nEstimation and tests are done by gretl "
            "(with the EViewsCompat package); the command window accepts EViews commands, "
            "translated by evprg2hansl."))

    # -- helpers ----------------------------------------------------------
    def wf_title(self) -> str:
        p = self.engine.wf.path
        return os.path.splitext(os.path.basename(p))[0].upper() if p else "UNTITLED"

    def error(self, msg: str):
        self.log_append("Error: " + msg)
        QMessageBox.warning(self, "Error", msg[:2000])

    def log_append(self, text: str):
        self.log.appendPlainText(text)

    def add_window(self, key: str, w: QWidget, size=(640, 420), kind: str = "bundle"):
        old = self.windows.get(key)
        if old is not None:
            try:
                old.parentWidget().close()
            except RuntimeError:
                pass
        sub = self.mdi.addSubWindow(w)
        sub.setAttribute(Qt.WA_DeleteOnClose)
        sub.setWindowIcon(_icon(kind))
        sub.resize(*size)
        sub.show()
        self.windows[key] = w
        return sub

    def refresh(self):
        self.engine.refresh()
        if self.wf_window:
            self.wf_window.populate()
        wf = self.engine.wf
        self.statusBar().showMessage(
            f"Path = {os.path.dirname(wf.path) if wf.path else os.path.expanduser('~')}    "
            f"WF = {self.wf_title().lower()}    Sample: {wf.sample_first} {wf.sample_last}")

    def show_workfile(self):
        if self.wf_window is None:
            self.wf_window = WorkfileWindow(self)
            sub = self.mdi.addSubWindow(self.wf_window)
            sub.setWindowIcon(_icon("workfile"))
            sub.resize(600, 380)
            sub.move(10, 10)
        self.wf_window.setWindowTitle(f"Workfile: {self.wf_title()} - ({self.engine.wf.path or 'untitled'})")
        self.wf_window.parentWidget().show()
        self.refresh()

    # -- command execution -----------------------------------------------
    def fix_case(self, line: str) -> str:
        """EViews names are case-insensitive: match typed names to existing objects."""
        wf = self.engine.wf
        names = {n.lower(): n for n in wf.series + wf.lists + wf.bundles + list(wf.scalars) + wf.strings}
        parts = re.split(r'("[^"]*")', line)       # quoted text (file names...) is left alone
        for i in range(0, len(parts), 2):
            parts[i] = re.sub(r"(?<![A-Za-z0-9_@!%$.])([A-Za-z]\w*)",
                              lambda m: names.get(m.group(1).lower(), m.group(1)), parts[i])
        return "".join(parts)

    def execute(self, line: str, hansl: bool = False):
        """Run an EViews command (translated) or, failing that, a gretl command."""
        self.log_append(f"> {line}")
        if not hansl:
            line = self.fix_case(line)
        before = set(self.engine.wf.bundles)
        if hansl:
            cmds = [line]
        else:
            try:
                cmds = tr.translate_line(line, self.ctx)
            except tr.Ignored as e:
                self.log_append(f"  (no effect here: {e})")
                return
            except ValueError:
                cmds = [line]            # not EViews: pass through as a gretl command
        cmds = [c for c in cmds if c.strip()]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            text = "\n".join(cmds)
            text = re.sub(r'--output="(plot\d+\.png)"', "", text)
            plots = [c for c in cmds if c.startswith("gnuplot")]
            if plots:
                for c in plots:
                    c = re.sub(r'\s--output=\S+', "", c)
                    self.graph_window(c, "Graph: " + " ".join(c.split()[1:3]))
                rest = [c for c in cmds if not c.startswith("gnuplot")]
                text = "\n".join(rest)
            out = self.engine.run(text) if text.strip() else []
            if out:
                self.log_append("\n".join(out))
            if self.engine.is_error(out):
                self.error("\n".join(out).strip())
        finally:
            QApplication.restoreOverrideCursor()
        if self.engine.wf.nobs_full or re.match(r"\s*(open|nulldata)", text if not hansl else line):
            self.refresh()
        new = [b for b in self.engine.wf.bundles if b not in before]
        for b in new:
            if b.startswith("eq_untitled"):
                self.open_object((b, "equation"))

    # -- objects ----------------------------------------------------------
    def open_object(self, obj):
        name, kind = obj
        if kind == "series":
            self.add_window(name, SeriesWindow(self, name), (420, 420), "series")
        elif kind == "group":
            self.add_window(name, GroupWindow(self, name), (520, 420), "group")
        elif kind == "equation":
            self.add_window(name, EquationWindow(self, name), (700, 520), "equation")
        elif kind == "scalar":
            self.statusBar().showMessage(f"{name} = {self.engine.wf.scalars.get(name)}")
        elif kind == "string":
            self.log_append("\n".join(self.engine.run(f"print {name}")))

    def graph_window(self, cmd: str, title: str):
        w = ObjectWindow(self, title)
        w.set_toolbar(_toolbar([("Freeze", w.freeze)]))
        try:
            w.show_image(self.engine.plot(cmd))
        except GretlError as e:
            self.error(str(e))
            return
        self.add_window(title + str(id(w)), w, (680, 500))

    def delete_object(self, name, ask=True):
        if ask and QMessageBox.question(self, "Delete", f"Delete {name}?") != QMessageBox.Yes:
            return
        self.execute(f"delete {name}", hansl=True)
        w = self.windows.pop(name, None)
        if w is not None:
            try:
                w.parentWidget().close()
            except RuntimeError:
                pass

    def rename_object(self, name):
        new, ok = QInputDialog.getText(self, "Object Name", "Name to identify object:", text=name)
        if ok and new.strip() and new.strip() != name:
            self.execute(f"rename {name} {new.strip()}", hansl=True)

    # -- file -------------------------------------------------------------
    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open", os.path.expanduser("~"),
            "Data files (*.gdt *.gdtb *.wf1 *.csv *.txt *.xlsx *.xls *.dta *.sav);;All files (*)")
        if path:
            self.open_file(path)

    def open_file(self, path: str):
        try:
            self.engine.open(path)
        except GretlError as e:
            self.error(str(e))
            return
        self.ctx = tr.Ctx()
        self.ctx.plot_files = True
        for w in list(self.windows):
            try:
                self.windows.pop(w).parentWidget().close()
            except RuntimeError:
                pass
        self.log_append(f"Opened {path}")
        self.show_workfile()

    def new_workfile(self):
        freq = QComboBox()
        freq.addItems(["Annual", "Quarterly", "Monthly", "Daily - 5 day week", "Undated"])
        start, end = QLineEdit("1990"), QLineEdit("2024")
        d = _form_dialog(self, "Workfile Create", [("Frequency:", freq), ("Start date:", start), ("End date:", end)])
        if not d:
            return
        code = {"Annual": "a", "Quarterly": "q", "Monthly": "m", "Daily - 5 day week": "d5", "Undated": "u"}[freq.currentText()]
        try:
            if code == "u":
                self.engine.run(f"nulldata {int(end.text())}", check=True)
                self.engine.wf.path = None
                self.engine.wf.first, self.engine.wf.last, self.engine.wf.nobs_full = "1", end.text(), int(end.text())
            else:
                self.engine.new_workfile(code, start.text().strip(), end.text().strip())
        except (GretlError, ValueError) as e:
            self.error(str(e))
            return
        self.show_workfile()

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save workfile", "", "gretl data (*.gdt)")
        if path:
            if not path.endswith(".gdt"):
                path += ".gdt"
            self.execute(f'store "{path}"', hansl=True)
            self.engine.wf.path = path
            self.show_workfile()

    def run_program_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Run EViews program", os.path.expanduser("~"), "EViews programs (*.prg)")
        if path:
            self.run_program(path)

    def run_program(self, path: str):
        with open(path, encoding="utf-8", errors="replace") as f:
            hansl, todos, ignored = tr.translate_full(f.read(), plot_files=True)
        tmp = self.engine.tmpdir
        hansl = re.sub(r'--output="(plot\d+\.png)"', lambda m: f'--output="{os.path.join(tmp, "prg_" + m.group(1))}"', hansl)
        inp = os.path.join(tmp, "program.inp")
        with open(inp, "w") as f:
            f.write(hansl)
        self.log_append(f"Running {path} ({len(todos)} untranslated line(s), {len(ignored)} ignored)")
        for n, t in todos:
            self.log_append(f"  TODO line {n}: {t}")
        before = set(os.listdir(tmp))
        self.engine.run(f'set workdir "{os.path.dirname(path)}"')
        out = self.engine.run(f'run "{inp}"')
        self.log_append("\n".join(out))
        self.output_dock.show()
        if self.engine.is_error(out):
            self.error("The program stopped with an error; see the Output log.")
        if self.engine.wf.nobs_full == 0:
            try:
                info = self.engine._query('printf "%s|%s|%d|%d\\n", obslabel(1), obslabel($nobs), $nobs, $pd')
                first, last, n, pd = info.split("|")
                wf = self.engine.wf
                wf.first, wf.last, wf.nobs_full, wf.pd = first, last, int(n), int(pd)
            except GretlError:
                pass
        for fn in sorted(set(os.listdir(tmp)) - before):
            if fn.startswith("prg_plot") and fn.endswith(".png"):
                w = ObjectWindow(self, f"Graph: {fn[4:-4]}")
                w.set_toolbar(_toolbar([("Freeze", w.freeze)]))
                w.show_image(os.path.join(tmp, fn))
                self.add_window(fn, w, (620, 460))
        self.show_workfile()

    # -- Quick dialogs ----------------------------------------------------
    def sample_dialog(self):
        wf = self.engine.wf
        rng = QLineEdit(f"{wf.sample_first} {wf.sample_last}" if wf.sample_first else "@all")
        cond = QLineEdit()
        d = _form_dialog(self, "Sample", [("Sample range pairs (or @all):", rng), ("IF condition (optional):", cond)])
        if d:
            txt = rng.text().strip().replace(":", "q" if wf.pd == 4 else ("m" if wf.pd == 12 else ":"))
            self.execute(f"smpl {txt}" + (f" if {cond.text().strip()}" if cond.text().strip() else ""))

    def genr_dialog(self, prefill: str = ""):
        eq = QLineEdit(prefill)
        eq.setMinimumWidth(420)
        d = _form_dialog(self, "Generate Series by Equation", [("Enter equation:", eq)])
        if d and eq.text().strip():
            self.execute("series " + eq.text().strip())

    def show_dialog(self):
        names, ok = QInputDialog.getText(self, "Show", "Objects to show (space separated):")
        if ok and names.split():
            ns = names.split()
            known = dict((n.lower(), (n, k)) for n, k in
                         [(s, "series") for s in self.engine.wf.series] + [(b, "equation") for b in self.engine.wf.bundles]
                         + [(g, "group") for g in self.engine.wf.lists])
            if len(ns) == 1 and ns[0].lower() in known:
                self.open_object(known[ns[0].lower()])
            else:
                self.execute(f"group untitled {' '.join(ns)}")
                self.open_object(("untitled", "group"))

    def graph_dialog(self):
        names, ok = QInputDialog.getText(self, "Graph", "Series to graph (space separated):")
        if ok and names.split():
            self.graph_window(f"gnuplot {names} --time-series --with-lines", "Graph: " + names)

    def stats_dialog(self):
        name, ok = QInputDialog.getText(self, "Series Statistics", "Series name:")
        if ok and name.strip():
            w = SeriesWindow(self, name.strip())
            self.add_window(name.strip(), w, (420, 420))
            w.run_text(f"summary {name.strip()}\nnormtest {name.strip()} --jbera")

    def equation_dialog(self, name: str | None = None, spec: str = "", window=None):
        d = QDialog(self)
        d.setWindowTitle("Equation Estimation")
        lay = QVBoxLayout(d)
        lay.addWidget(QLabel("Equation specification\nDependent variable followed by the list of regressors, "
                             "e.g.  dlog(cons) c dlog(gdp) cons(-1)"))
        sp = QPlainTextEdit(spec)
        sp.setFont(MONO)
        sp.setFixedHeight(90)
        lay.addWidget(sp)
        form = QFormLayout()
        method = QComboBox()
        method.addItems(["LS - Least Squares (NLS and ARMA)", "ARCH - GARCH(1,1)"])
        cov = QComboBox()
        cov.addItems(["Ordinary", "White", "HAC (Newey-West)"])
        wf = self.engine.wf
        smp = QLineEdit(f"{wf.sample_first} {wf.sample_last}")
        form.addRow("Method:", method)
        form.addRow("Sample:", smp)
        form.addRow("Coefficient covariance:", cov)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        if d.exec() != QDialog.Accepted or not sp.toPlainText().strip():
            return
        if name is None:
            self.eq_count += 1
            name = f"eq{self.eq_count:02d}"
            while name in self.engine.wf.bundles:
                self.eq_count += 1
                name = f"eq{self.eq_count:02d}"
        s = " ".join(sp.toPlainText().split())
        smp_txt = smp.text().strip()
        if smp_txt and smp_txt != f"{wf.sample_first} {wf.sample_last}":
            self.execute("smpl " + smp_txt.replace(":", "q" if wf.pd == 4 else ("m" if wf.pd == 12 else ":")))
        if method.currentIndex() == 1:
            self.execute(f"equation {name}.arch(1,1) {s}")
            return
        opt = {0: "", 1: "(cov=white)", 2: "(cov=hac)"}[cov.currentIndex()]
        self.execute(f"equation {name}.ls{opt} {s}")
        if name in self.engine.wf.bundles:
            self.open_object((name, "equation"))

    def closeEvent(self, e):
        self.engine.close()
        super().closeEvent(e)


STYLE = """
QMainWindow, QWidget { font-size: 13px; }
#objbar { background: #eceff3; border-bottom: 1px solid #b8bec7; }
#objbtn { padding: 1px 6px; border: 1px solid #a9b0ba; border-radius: 2px; background: #f7f8fa; }
#objbtn:hover { background: #ffffff; }
#objbtn:disabled { color: #9aa0a8; }
#wfinfo { background: #f7f8fa; border-bottom: 1px solid #d0d4da; }
#wftab { background: #eceff3; border-top: 1px solid #b8bec7; padding: 2px; }
QPlainTextEdit { background: #ffffff; }
QListWidget { background: #ffffff; }
"""


def light_palette() -> QPalette:
    """Fixed light palette: the interface must not follow macOS dark mode."""
    p = QPalette()
    for role, c in [(QPalette.Window, "#eceff3"), (QPalette.WindowText, "#1b1f24"),
                    (QPalette.Base, "#ffffff"), (QPalette.AlternateBase, "#f4f6f8"),
                    (QPalette.Text, "#1b1f24"), (QPalette.Button, "#f2f4f7"),
                    (QPalette.ButtonText, "#1b1f24"), (QPalette.ToolTipBase, "#ffffe0"),
                    (QPalette.ToolTipText, "#1b1f24"), (QPalette.Highlight, "#2f6fb3"),
                    (QPalette.HighlightedText, "#ffffff"), (QPalette.PlaceholderText, "#8a9099"),
                    (QPalette.BrightText, "#c62828"), (QPalette.Link, "#1565c0")]:
        p.setColor(role, QColor(c))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor("#9aa0a8"))
    return p


def main(argv=None):
    app = QApplication(argv or sys.argv)
    app.setStyle("Fusion")
    app.setPalette(light_palette())
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    args = (argv or sys.argv)[1:]
    if args:
        if args[0].lower().endswith(".prg"):
            w.run_program(os.path.abspath(args[0]))
        else:
            w.open_file(os.path.abspath(args[0]))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
