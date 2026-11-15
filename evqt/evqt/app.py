"""EViews-style main window on top of gretl (GretlEngine)."""
from __future__ import annotations

import os
import re
import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import (QAction, QColor, QPalette, QFont, QFontDatabase, QIcon, QKeySequence,
                           QPainter, QPen, QPixmap, QTextCursor)
from PySide6.QtWidgets import (QApplication, QComboBox, QSizePolicy, QTabBar, QSplitter, QAbstractItemView, QDialog, QDialogButtonBox,
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
    colors = {"series": "#2e7d32", "equation": "#1565c0", "group": "#6a1b9a", "var": "#ad1457",
              "vecm": "#c62828", "system": "#283593", "model": "#4e342e",
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
                 "workfile": "W", "var": "V", "vecm": "V", "forecast": "F", "system": "S", "model": "M"}.get(kind, "?")
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

    def show_table(self, header: list[str], rows: list[list[str]], obsno: list[int] | None = None):
        t = self.table
        try:
            t.itemChanged.disconnect(self._cell_changed)
        except (RuntimeError, TypeError):
            pass
        self._obsno = obsno
        self._header = header
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
        editable = bool(getattr(self, "editing", False) and obsno)
        t.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                          | QAbstractItemView.AnyKeyPressed if editable else QAbstractItemView.NoEditTriggers)
        t.setStyleSheet("QTableWidget { background: #fffdf0; }" if editable else "")
        if editable:
            t.itemChanged.connect(self._cell_changed)
        self.stack.setCurrentWidget(t)

    def _cell_changed(self, item: QTableWidgetItem):
        """Write an edited cell back to gretl (Edit+/- mode)."""
        name = self._header[item.column() + 1]
        obs = self._obsno[item.row()]
        try:
            self.main.engine.set_value(name, obs, item.text())
            self.main.log_append(f"> {name}[{self.table.verticalHeaderItem(item.row()).text()}] = {item.text()}")
        except (GretlError, ValueError) as e:
            self.main.error(f"Not a number: {item.text()!r}" if isinstance(e, ValueError) else str(e))
            self.spreadsheet()
            return
        self.main.refresh_views(exclude=self)

    def toggle_edit(self):
        self.editing = not getattr(self, "editing", False)
        self.spreadsheet()

    def spreadsheet(self):
        pass

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
            ("Edit+/-", self.toggle_edit),
            ("Sample", main.sample_dialog),
            ("Genr", lambda: main.genr_dialog()),
        ]))
        self.spreadsheet()

    def spreadsheet(self):
        try:
            h, rows, obs = self.main.engine.series_values([self.name], with_obs=True)
            self.show_table(h, rows, obs)
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
            ("Edit+/-", self.toggle_edit),
            ("Sample", main.sample_dialog),
        ]))
        self.spreadsheet()

    def members(self) -> list[str]:
        out = self.main.engine.run(f'printf "%s\\n", varname({self.name})')
        return [x for x in "".join(out).strip().split(",") if x]

    def spreadsheet(self):
        try:
            h, rows, obs = self.main.engine.series_values([self.name], with_obs=True)
            self.show_table(h, rows, obs)
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
            ("Forecast", self.forecast),
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

    def forecast(self):
        """EViews Forecast dialog: series names, method and forecast sample."""
        dep, lvl = self.main.engine.dep_info(self.name)
        wf = self.main.engine.wf
        target = QComboBox()
        if lvl:
            target.addItems([lvl.upper(), dep])         # EViews default: the series itself
        else:
            target.addItems([dep])
        fname, sename = QLineEdit(), QLineEdit()
        sename.setPlaceholderText("optional")

        def _name(_=None):
            t = target.currentText()
            fname.setText((re.sub(r"\W+", "_", t.lower()).strip("_") or "y") + "f")
        target.currentIndexChanged.connect(_name)
        _name()
        method = QComboBox()
        method.addItems(["Dynamic forecast", "Static forecast"])
        smp = QLineEdit(f"{wf.sample_first} {wf.sample_last}")
        d = _form_dialog(self, f"Forecast: {self.name.upper()}", [
            ("Series to forecast:", target), ("Forecast name:", fname),
            ("S.E. (optional):", sename), ("Method:", method), ("Forecast sample:", smp)])
        if not d or not fname.text().strip():
            return
        level = bool(lvl) and target.currentIndex() == 0
        m = self.main
        if smp.text().strip() != f"{wf.sample_first} {wf.sample_last}":
            m.execute("smpl " + m.eviews_dates(smp.text().strip()))
        try:
            text, png = m.engine.forecast(self.name, fname.text().strip(), sename.text().strip(),
                                          method.currentIndex() == 0, level)
        except GretlError as e:
            m.error(str(e))
            return
        m.forecast_window(f"Forecast: {fname.text().strip()}", text, png)
        m.refresh()


class VarWindow(ObjectWindow):
    def __init__(self, main, name):
        super().__init__(main, f"Var: {name.upper()}   Workfile: {main.wf_title()}")
        self.name = name
        self.vec = main.engine.wf.kinds.get(name) == "vecm"
        self.set_toolbar(_toolbar([
            ("View", [("Estimation Output", self.output),
                      ("Lag Structure: Granger Causality / Block Exogeneity Tests", self.granger),
                      ("Cointegration Test...", self.coint),
                      ("Lag Structure: Lag Length Criteria...", self.laglen),
                      ("Impulse Response...", self.impulse),
                      ("Variance Decomposition...", self.decomp),
                      ("Residuals: Graphs", self.resid_graph)]),
            ("Proc", [("Make Residuals", self.make_resids),
                      ("Estimate Structural Factorization...", self.svar)]),
            ("Object", [("Delete", lambda: main.delete_object(name))]),
            ("|", None),
            ("Name", lambda: main.rename_object(name)),
            ("Freeze", self.freeze),
            ("Estimate", self.estimate),
            ("Stats", self.output),
            ("Impulse", self.impulse),
            ("Resids", self.resid_graph),
        ]))
        self.output()

    def output(self):
        self.run_text(f"ev_vecprint(&{self.name})" if self.vec else f"ev_varprint(&{self.name})")

    def granger(self):
        if self.vec:
            self.main.error("Granger causality tests are available for unrestricted VARs.")
            return
        self.run_text(f"ev_vargranger({self.name})")

    def svar(self):
        """Structural factorization: A-B pattern matrices or long-run restrictions."""
        n = int(float("".join(self.main.engine.run(f'printf "%d\\n", {self.name}.n')).strip() or 0))
        kind = QComboBox()
        kind.addItems(["Short-run pattern: A e = B u", "Long-run (Blanchard-Quah)"])
        lower = "; ".join(" ".join("1" if i == j else ("NA" if j < i else "0") for j in range(n)) for i in range(n))
        diag = "; ".join(" ".join("NA" if i == j else "0" for j in range(n)) for i in range(n))
        ea, eb = QLineEdit(lower), QLineEdit(diag)
        for e in (ea, eb):
            e.setFont(MONO)
            e.setMinimumWidth(380)
        d = _form_dialog(self, "Structural Factorization", [
            ("Restriction type:", kind),
            ("A (rows separated by ';', NA = estimated):", ea),
            ("B:", eb)])
        if not d:
            return
        try:
            if kind.currentIndex() == 1:
                self.show_lines(self.main.engine.run(f"ev_svar_lr(&{self.name})", check=True))
            else:
                def mat(txt):
                    rows = [r.replace(",", " ").split() for r in txt.split(";") if r.strip()]
                    if len(rows) != n or any(len(r) != n for r in rows):
                        raise ValueError(f"A and B must be {n} x {n}")
                    return "{" + "; ".join(", ".join("NA" if v.upper() == "NA" else str(float(v)) for v in r)
                                           for r in rows) + "}"
                self.main.engine.run(f"matrix ev_A = {mat(ea.text())}\nmatrix ev_B = {mat(eb.text())}", check=True)
                self.show_lines(self.main.engine.run(f"ev_svar(&{self.name}, ev_A, ev_B)", check=True))
        except (GretlError, ValueError) as e:
            self.main.error(str(e))
            return
        self.main.log_append(f"{self.name}: structural factorization estimated; Impulse now uses structural shocks")

    def coint(self):
        names = " ".join(self.main.engine.strings(f"{self.name}.ytok"))
        case, ok = QInputDialog.getItem(self, "Johansen Cointegration Test", "Deterministic trend case:",
                                        ["a: no intercept or trend", "b: intercept in CE", "c: intercept in CE and VAR",
                                         "d: intercept and trend in CE", "e: quadratic trend"], 2, False)
        if not ok:
            return
        k, ok = QInputDialog.getInt(self, "Johansen Cointegration Test", "Lags (in first differences):", 2, 1, 20)
        if ok:
            self.run_text(f'ev_coint("{names}", dataset, "{case[0]}", {k})')

    def laglen(self):
        k, ok = QInputDialog.getInt(self, "Lag Specification", "Lags to include:", 8, 1, 40)
        if ok:
            self.run_text(f"ev_varlaglen({self.name}, dataset, {k})")

    def _horizon(self, title):
        return QInputDialog.getInt(self, title, "Periods:", 10, 1, 200)

    def impulse(self):
        h, ok = self._horizon("Impulse Responses")
        if ok:
            path = self.main.engine.tmp_png()
            try:
                self.main.engine.run(f'ev_varirfplot({self.name}, {h}, "{path}")', check=True)
                self.show_image(path)
            except GretlError as e:
                self.main.error(str(e))

    def decomp(self):
        h, ok = self._horizon("Variance Decomposition")
        if ok:
            self.run_text(f"ev_vardecomp({self.name}, {h})")

    def resid_graph(self):
        e = self.main.engine
        try:
            e.run(f"matrix ev_M = {self.name}.sys.uhat\ncnameset(ev_M, {self.name}.ylab)", check=True)
            self.run_plot("gnuplot --matrix=ev_M --time-series --with-lines")
        except GretlError as ex:
            self.main.error(str(ex))

    def make_resids(self):
        e = self.main.engine
        n = int(float("".join(e.run(f'printf "%d\\n", {self.name}.n')).strip() or 0))
        cmds = [f"series resid{k:02d} = ev_varresid({self.name}, {k})" for k in range(1, n + 1)]
        self.main.execute("\n".join(cmds), hansl=True)

    def estimate(self):
        spec = "".join(self.main.engine.run(f'printf "%s\\n", {self.name}.spec')).strip()
        self.main.var_dialog(name=self.name, spec=spec, vec=self.vec)


class SystemWindow(ObjectWindow):
    """System object: specification text (EViews syntax) and estimation output."""

    def __init__(self, main, name):
        super().__init__(main, f"System: {name.upper()}   Workfile: {main.wf_title()}")
        self.name = name
        self.set_toolbar(_toolbar([
            ("View", [("System Specification", self.show_spec),
                      ("Estimation Output", self.output),
                      ("Residuals: Graphs", self.resid_graph)]),
            ("Proc", [("Make Residuals", self.make_resids)]),
            ("Object", [("Delete", lambda: main.delete_object(name))]),
            ("|", None),
            ("Name", lambda: main.rename_object(name)),
            ("Freeze", self.freeze),
            ("Spec", self.show_spec),
            ("Estimate", self.estimate),
            ("Stats", self.output),
        ]))
        known = main.ctx.systems.get(name)
        text = main.system_specs.get(name) or (
            "\n".join(known["eqs"] + ([f"inst {known['inst']}"] if known["inst"] else [])) if known else "")
        self.spec = QPlainTextEdit(text)
        self.spec.setFont(MONO)
        self.spec.setPlaceholderText(
            "One equation per line, linear in the coefficients, e.g.\n"
            "dlog(cons) = c(1) + c(2)*dlog(gdp)\n"
            "dlog(inv) = c(3) + c(2)*dlog(gdp) + c(4)*ffr\n"
            "inst ffr(-1) dlog(gdp(-1)) ffr      (instruments, for 2SLS / 3SLS)")
        self.stack.addWidget(self.spec)
        if name in main.engine.wf.bundles:
            self.output()
        else:
            self.show_spec()

    def show_spec(self):
        self.stack.setCurrentWidget(self.spec)

    def output(self):
        if self.name in self.main.engine.wf.bundles:
            self.run_text(f"ev_sysprint(&{self.name})")
        else:
            self.show_spec()

    def estimate(self):
        lines = [ln.strip() for ln in self.spec.toPlainText().splitlines() if ln.strip()]
        if not lines:
            self.main.error("Write the system's equations in the specification first.")
            self.show_spec()
            return
        methods = {"Ordinary Least Squares": "ls", "Weighted Least Squares": "wls",
                   "Seemingly Unrelated Regression": "sur", "Two-Stage Least Squares": "tsls",
                   "Weighted Two-Stage Least Squares": "wtsls", "Three-Stage Least Squares": "3sls",
                   "Full Information Maximum Likelihood": "fiml",
                   "Generalized Method of Moments (White weighting)": "gmm"}
        meth, ok = QInputDialog.getItem(self, "System Estimation", "Estimation method:", list(methods), 2, False)
        if not ok:
            return
        code = methods[meth]
        self.main.system_specs[self.name] = self.spec.toPlainText()
        self.main.execute(f"system {self.name}")
        for ln in lines:
            self.main.execute(f"{self.name}.append {ln}", quiet=True)
        self.main.execute(f"{self.name}.{code}")
        if self.name in self.main.engine.wf.bundles:
            self.output()

    def resid_graph(self):
        try:
            self.main.engine.run(f"matrix ev_M = {self.name}.uhat\ncnameset(ev_M, {self.name}.deps)", check=True)
            self.run_plot("gnuplot --matrix=ev_M --time-series --with-lines")
        except GretlError as e:
            self.main.error(str(e))

    def make_resids(self):
        n = int(float("".join(self.main.engine.run(f'printf "%d\\n", {self.name}.n')).strip() or 0))
        self.main.execute("\n".join(f"series resid{k:02d} = ev_sysresid({self.name}, {k})"
                                     for k in range(1, n + 1)), hansl=True)


class ModelWindow(ObjectWindow):
    """Model object: equations from the workfile plus identities, solved together."""

    def __init__(self, main, name):
        super().__init__(main, f"Model: {name.upper()}   Workfile: {main.wf_title()}")
        self.name = name
        self.set_toolbar(_toolbar([
            ("View", [("Equations", self.show_spec), ("Solution Summary", self.summary),
                      ("Graph: Actual and Solution...", self.graph)]),
            ("Object", [("Delete", lambda: main.delete_object(name))]),
            ("|", None),
            ("Name", lambda: main.rename_object(name)),
            ("Freeze", self.freeze),
            ("Equations", self.show_spec),
            ("Solve", self.solve),
        ]))
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.addWidget(QLabel("Equations to include (estimated least-squares or explicit equations):"))
        self.eqlist = QListWidget()
        wf = main.engine.wf
        saved = main.model_specs.get(name, {})
        for b in wf.bundles:
            if wf.kinds.get(b) == "equation":
                it = QListWidgetItem(b)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if b in saved.get("eqs", []) else Qt.Unchecked)
                self.eqlist.addItem(it)
        lay.addWidget(self.eqlist)
        lay.addWidget(QLabel("Identities, one per line (e.g. gdp = cons + inv + oth):"))
        self.ids = QPlainTextEdit(saved.get("ids", ""))
        self.ids.setFont(MONO)
        self.ids.setFixedHeight(90)
        lay.addWidget(self.ids)
        self.specw = box
        self.stack.addWidget(box)
        self.names: list[str] = []
        self.show_spec()

    def show_spec(self):
        self.stack.setCurrentWidget(self.specw)

    def summary(self):
        if self.last_summary:
            self.show_text(self.last_summary)

    last_summary = ""

    def solve(self):
        eqs = [self.eqlist.item(i).text() for i in range(self.eqlist.count())
               if self.eqlist.item(i).checkState() == Qt.Checked]
        ids = [ln.strip() for ln in self.ids.toPlainText().splitlines() if ln.strip()]
        if not eqs and not ids:
            self.main.error("Choose equations or write identities first.")
            return
        mode, ok = QInputDialog.getItem(self, "Model Solution", "Solution type:",
                                        ["Dynamic solution", "Static solution"], 0, False)
        if not ok:
            return
        m = self.main
        m.model_specs[self.name] = {"eqs": eqs, "ids": self.ids.toPlainText()}
        try:
            cmds = [f"model {self.name}"]
            if eqs:
                cmds.append(f"{self.name}.merge {' '.join(eqs)}")
            cmds += [f"{self.name}.append @identity {ln}" for ln in ids]
            cmds.append(f"{self.name}.solve" + ("(d=s)" if mode.startswith("Static") else ""))
            lines = []
            for c in cmds:
                lines += tr.translate_line(m.fix_case(c), m.ctx)
        except ValueError as e:
            m.error(str(e))
            return
        out = m.engine.run("\n".join(x for x in lines if x.strip()))
        m.log_append("\n".join(out))
        if m.engine.is_error(out):
            m.error("\n".join(out).strip())
            return
        self.names = [re.sub(r"\s*=.*", "", ln.split("ev_modelseries")[0]).replace("series ", "").strip()
                      for ln in lines if "ev_modelseries" in ln]
        self.last_summary = "\n".join(out).strip()
        m.engine.wf.dirty = True
        m.refresh()
        self.show_text(self.last_summary)

    def graph(self):
        if not self.names:
            self.main.error("Solve the model first.")
            return
        sol, ok = QInputDialog.getItem(self, "Graph", "Variable:", self.names, 0, False)
        if ok:
            self.run_plot(f"gnuplot {sol[:-2]} {sol} --time-series --with-lines")


class ForecastWindow(ObjectWindow):
    """Forecast graph with +/- 2 S.E. bands above the evaluation table."""

    def __init__(self, main, title, text, png):
        super().__init__(main, title)
        self.set_toolbar(_toolbar([("Freeze", self.freeze)]))
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.image)
        split.addWidget(self.text)
        self.image.show()      # they were hidden while inside the stacked widget
        self.text.show()
        split.setSizes([360, 200])
        self.stack.addWidget(split)
        self.stack.setCurrentWidget(split)
        self.image.set_image(QPixmap(png))
        self.text.setPlainText(text)


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
            ("Save", main.save),
            ("Freeze", None),
            ("Details+/-", self.toggle_details),
            ("Show", main.show_dialog),
            ("Fetch", main.fetch_dialog),
            ("Store", self.store_selected),
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
        # page tabs, as at the bottom of an EViews workfile window
        self.tabs = QTabBar()
        self.tabs.setObjectName("wftabs")
        self.tabs.setShape(QTabBar.RoundedSouth)
        self.tabs.setExpanding(False)
        self.tabs.setDocumentMode(True)
        self.tabs.tabBarClicked.connect(self._tab_clicked)
        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._tab_menu)
        lay.addWidget(self.tabs)

    def populate(self):
        wf = self.main.engine.wf
        self.range_lbl.setText(f"Range:  {wf.first} {wf.last}  --  {wf.nobs_full} obs")
        self.sample_lbl.setText(f"Sample: {wf.sample_first} {wf.sample_last}  --  {wf.sample_nobs} obs")
        self.list.clear()
        objs = [(b, wf.kinds.get(b, "bundle")) for b in wf.bundles
                if wf.kinds.get(b) in ("equation", "var", "vecm", "system", "model")
                and wf.obj_page.get(b, wf.page) == wf.page]
        items = [(n, "series") for n in wf.series] + [(n, "group") for n in wf.lists] \
            + objs + [(n, "scalar") for n in wf.scalars] + [(n, "string") for n in wf.strings]
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
        self._fill_tabs()

    def _fill_tabs(self):
        wf = self.main.engine.wf
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for p in wf.pages:
            self.tabs.addTab(p)
        self.tabs.addTab("New Page")
        self.tabs.setCurrentIndex(wf.pages.index(wf.page))
        self.tabs.blockSignals(False)

    def _tab_clicked(self, i):
        wf = self.main.engine.wf
        if i < 0:
            return
        if i == len(wf.pages):
            self.main.new_page_dialog()
        else:
            self.main.select_page(wf.pages[i])

    def _tab_menu(self, pos):
        i = self.tabs.tabAt(pos)
        wf = self.main.engine.wf
        if i < 0 or i >= len(wf.pages):
            return
        page = wf.pages[i]
        m = QMenu(self)
        m.addAction("Rename Page...", lambda: self.main.rename_page_dialog(page))
        m.addAction("Delete Page", lambda: self.main.delete_page(page))
        m.exec(self.tabs.mapToGlobal(pos))

    def store_selected(self):
        names = [n for n, k in self.selected() if k == "series"]
        if not names:
            QMessageBox.information(self, "Store", "Select one or more series in the workfile first.")
            return
        self.main.store_dialog(names)

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
        self.system_specs: dict[str, str] = {}
        self.model_specs: dict[str, dict] = {}

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
        a = f.addAction("Save", self.save)
        a.setShortcut(QKeySequence.Save)
        f.addAction("Save As (.gdt)...", self.save_as)
        f.addSeparator()
        f.addAction("Fetch from Database...", self.fetch_dialog)
        f.addAction("New Page...", self.new_page_dialog)
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
        q.addAction("Estimate VAR...", lambda: self.var_dialog())
        q.addAction("Estimate System...", self.new_system)
        q.addAction("Make Model...", self.new_model)
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
        self._update_titles()
        wf = self.engine.wf
        self.statusBar().showMessage(
            f"Path = {os.path.dirname(wf.path) if wf.path else os.path.expanduser('~')}    "
            f"WF = {self.wf_title().lower()}    Sample: {wf.sample_first} {wf.sample_last}")

    def _update_titles(self):
        wf = self.engine.wf
        star = "*" if wf.dirty else ""
        self.setWindowTitle(f"evqt — {self.wf_title()}{star}")
        if self.wf_window:
            self.wf_window.setWindowTitle(f"Workfile: {self.wf_title()}{star} - ({wf.path or 'untitled'})")

    def show_workfile(self):
        if self.wf_window is None:
            self.wf_window = WorkfileWindow(self)
            sub = self.mdi.addSubWindow(self.wf_window)
            sub.setWindowIcon(_icon("workfile"))
            sub.resize(600, 380)
            sub.move(10, 10)
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

    def execute(self, line: str, hansl: bool = False, quiet: bool = False):
        """Run an EViews command (translated) or, failing that, a gretl command."""
        if not quiet:
            self.log_append(f"> {line}")
        self.engine.wf.dirty = True
        if not hansl:
            line = self.fix_case(line)
        before = set(self.engine.wf.bundles)
        if not hansl and self._native_command(line):
            return
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
            # graphs drawn by package functions (VAR impulse, forecast) go to temp files
            pngs = []

            def _png(m):
                pngs.append(self.engine.tmp_png())
                return f'"{pngs[-1]}"'
            text = re.sub(r'"plot\d+\.png"', _png, text)
            out = self.engine.run(text) if text.strip() else []
            for pth in pngs:
                if os.path.exists(pth):
                    w = ObjectWindow(self, "Graph")
                    w.set_toolbar(_toolbar([("Freeze", w.freeze)]))
                    w.show_image(pth)
                    self.add_window(pth, w, (760, 560))
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
        self.refresh_views()

    def _native_command(self, line: str) -> bool:
        """Commands handled by the interface itself (workfile pages, opening files)."""
        mo = re.match(r"(\w+)(?:\(([^)]*)\))?\s*(.*)", line.strip())
        if not mo:
            return False
        cmd, opts, rest = mo.group(1).lower(), mo.group(2) or "", mo.group(3).split()
        try:
            if cmd == "wfopen" and rest:
                self.open_file(os.path.expanduser(" ".join(rest).strip('"')))
            elif cmd == "pagecreate":
                name = tr._opts(opts).get("page") or f"untitled{len(self.engine.wf.pages) + 1}"
                if rest and rest[0].lower() == "u":
                    self.engine.new_page(name, "u", "", rest[1])
                else:
                    self.engine.new_page(name, rest[0].lower(), rest[1], rest[2])
            elif cmd == "pageselect" and rest:
                self.select_page(rest[0])
                return True
            elif cmd == "pagedelete":
                self.delete_page(rest[0] if rest else self.engine.wf.page, ask=False)
                return True
            elif cmd == "pagerename" and len(rest) >= 2:
                self.engine.rename_page(rest[0], rest[1])
            else:
                return False
        except (GretlError, IndexError, ValueError) as e:
            self.error(str(e))
            return True
        self.show_workfile()
        return True

    def refresh_views(self, exclude=None):
        """Re-read open spreadsheets after data changed."""
        for w in list(self.windows.values()):
            if w is exclude or not isinstance(w, (SeriesWindow, GroupWindow)):
                continue
            try:
                if w.stack.currentWidget() is w.table:
                    w.spreadsheet()
            except RuntimeError:
                pass

    def eviews_dates(self, txt: str) -> str:
        pd = self.engine.wf.pd
        return txt.replace(":", "q" if pd == 4 else ("m" if pd == 12 else ":"))

    def forecast_window(self, title, text, png):
        self.add_window(title, ForecastWindow(self, title, text, png), (720, 600), "forecast")

    # -- pages --------------------------------------------------------------
    def _close_object_windows(self):
        for k in list(self.windows):
            try:
                self.windows.pop(k).parentWidget().close()
            except RuntimeError:
                pass

    def select_page(self, page: str):
        if page == self.engine.wf.page:
            return
        try:
            self.engine.select_page(page)
        except GretlError as e:
            self.error(str(e))
            return
        self._close_object_windows()
        self.log_append(f"Page: {page}")
        self.show_workfile()

    def new_page_dialog(self):
        name = QLineEdit(f"untitled{len(self.engine.wf.pages) + 1}")
        freq = QComboBox()
        freq.addItems(["Annual", "Quarterly", "Monthly", "Daily - 5 day week", "Undated",
                       "Copy of the current page"])
        start, end = QLineEdit("1990"), QLineEdit("2024")
        d = _form_dialog(self, "Page Create", [("Page name:", name), ("Frequency:", freq),
                                               ("Start date:", start), ("End date (or obs):", end)])
        if not d:
            self._fill_tabs_later()
            return
        code = {"Annual": "a", "Quarterly": "q", "Monthly": "m", "Daily - 5 day week": "d5",
                "Undated": "u", "Copy of the current page": "copy"}[freq.currentText()]
        try:
            self.engine.new_page(name.text().strip(), code, start.text().strip(), end.text().strip())
        except (GretlError, ValueError) as e:
            self.error(str(e))
        self._close_object_windows()
        self.show_workfile()

    def _fill_tabs_later(self):
        if self.wf_window:
            self.wf_window._fill_tabs()

    def rename_page_dialog(self, page):
        new, ok = QInputDialog.getText(self, "Rename Page", "New page name:", text=page)
        if ok and new.strip() and new.strip() != page:
            try:
                self.engine.rename_page(page, new.strip())
            except GretlError as e:
                self.error(str(e))
            self.show_workfile()

    def delete_page(self, page, ask=True):
        if ask and QMessageBox.question(self, "Delete Page",
                                        f"Delete page {page} and the objects on it?") != QMessageBox.Yes:
            return
        try:
            self.engine.delete_page(page)
        except GretlError as e:
            self.error(str(e))
            return
        self._close_object_windows()
        self.show_workfile()

    # -- databases ----------------------------------------------------------
    def _db_path(self, save: bool) -> str:
        start = getattr(self, "_last_db", os.path.expanduser("~/evqt.bin"))
        if save:
            path, _ = QFileDialog.getSaveFileName(self, "Store to database", start,
                                                  "gretl database (*.bin)",
                                                  options=QFileDialog.Option.DontConfirmOverwrite)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Fetch from database", os.path.dirname(start),
                                                  "gretl database (*.bin)")
        if path and not path.endswith(".bin"):
            path += ".bin"
        if path:
            self._last_db = path
        return path

    def _fetch_source(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self, "Fetch from database or data file", os.path.dirname(getattr(self, "_last_db", os.path.expanduser("~/x"))),
            "Databases and data files (*.bin *.wf1 *.gdt *.gdtb *.csv *.txt *.xlsx *.xls *.ods *.dta *.sav);;"
            "gretl database (*.bin);;All files (*)")
        return path

    def store_dialog(self, names: list[str], path: str | None = None):
        path = path or self._db_path(save=True)
        if not path:
            return
        try:
            self.engine.db_store(path, names)
            self.log_append(f"Stored {' '.join(names)} in {path}")
            self.statusBar().showMessage(f"Stored {len(names)} series in {os.path.basename(path)}")
        except GretlError as e:
            self.error(str(e))

    def fetch_dialog(self, path: str | None = None, choose=None):
        path = path or self._fetch_source()
        if not path:
            return
        self._last_db = path
        try:
            # data files (.wf1, .csv, .xlsx ...) are read through a temporary database
            db = path if path.endswith(".bin") else self.engine.file_as_db(path)
            contents = self.engine.db_contents(db)
        except (OSError, GretlError) as e:
            self.error(f"Cannot read {os.path.basename(path)}: {e}")
            return
        if choose is None:
            d = QDialog(self)
            d.setWindowTitle(f"Fetch from {os.path.basename(path)}")
            lay = QVBoxLayout(d)
            lay.addWidget(QLabel("Series to fetch (frequency is converted to this page's by averaging):"))
            lst = QListWidget()
            lst.setSelectionMode(QListWidget.ExtendedSelection)
            for name, desc, rng in contents:
                it = QListWidgetItem(f"{name}    {rng}    {desc}")
                it.setData(Qt.UserRole, name)
                lst.addItem(it)
            lay.addWidget(lst)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(d.accept)
            bb.rejected.connect(d.reject)
            lay.addWidget(bb)
            d.resize(560, 360)
            if d.exec() != QDialog.Accepted:
                return
            choose = [it.data(Qt.UserRole) for it in lst.selectedItems()]
        if not choose:
            return
        try:
            self.engine.db_fetch(path, choose)
            self.log_append(f"Fetched {' '.join(choose)} from {path}")
        except GretlError as e:
            self.error(str(e))
        self.show_workfile()

    # -- objects ----------------------------------------------------------
    def open_object(self, obj):
        name, kind = obj
        if kind == "series":
            self.add_window(name, SeriesWindow(self, name), (420, 420), "series")
        elif kind == "group":
            self.add_window(name, GroupWindow(self, name), (520, 420), "group")
        elif kind == "equation":
            self.add_window(name, EquationWindow(self, name), (700, 520), "equation")
        elif kind in ("var", "vecm"):
            self.add_window(name, VarWindow(self, name), (760, 560), kind)
        elif kind == "system":
            self.add_window(name, SystemWindow(self, name), (720, 560), "system")
        elif kind == "model":
            self.add_window(name, ModelWindow(self, name), (680, 560), "model")
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

    def maybe_save(self) -> bool:
        """Ask about unsaved changes. False means: cancel what was going to happen."""
        if not self.engine.wf.dirty or not self.engine.wf.nobs_full:
            return True
        r = QMessageBox.question(self, "Unsaved changes",
                                 f"Save changes to {self.wf_title()}?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Save:
            return self.save()
        return True

    def save(self) -> bool:
        wf = self.engine.wf
        if not wf.path or not wf.path.endswith((".gdt", ".gdtb")):
            return self.save_as()
        try:
            written = self.engine.save()
        except GretlError as e:
            self.error(str(e))
            return False
        self.log_append("Saved " + ", ".join(written))
        self.statusBar().showMessage("Saved " + ", ".join(os.path.basename(w) for w in written))
        self._update_titles()
        return True

    def open_file(self, path: str):
        if not self.maybe_save():
            return
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

    def save_as(self) -> bool:
        start = self.engine.wf.path or os.path.expanduser("~/untitled.gdt")
        if not start.endswith(".gdt"):
            start = os.path.splitext(start)[0] + ".gdt"
        path, _ = QFileDialog.getSaveFileName(self, "Save workfile", start, "gretl data (*.gdt)")
        if not path:
            return False
        if not path.endswith(".gdt"):
            path += ".gdt"
        try:
            written = self.engine.save(path)
        except GretlError as e:
            self.error(str(e))
            return False
        self.log_append("Saved " + ", ".join(written))
        if len(written) > 1:
            QMessageBox.information(self, "Saved", "gretl keeps one dataset per file, so each page was saved "
                                    "separately:\n" + "\n".join(written))
        self.show_workfile()
        return True

    def run_program_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Run EViews program", os.path.expanduser("~"), "EViews programs (*.prg)")
        if path:
            self.run_program(path)

    def run_program(self, path: str):
        with open(path, encoding="utf-8", errors="replace") as f:
            hansl, todos, ignored = tr.translate_full(f.read(), plot_files=True)
        tmp = self.engine.tmpdir
        hansl = re.sub(r'"(plot\d+\.png)"', lambda m: f'"{os.path.join(tmp, "prg_" + m.group(1))}"', hansl)
        # in an interactive session gretl asks before replacing data: clear it first
        hansl = re.sub(r'(?m)^(\s*)open "(?![^"]*\.bin")', r'\1clear --dataset\n\1open "', hansl)
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

    def var_dialog(self, name: str | None = None, spec: str = "", vec: bool = False):
        """VAR Specification dialog: unrestricted VAR or vector error correction."""
        lags, endo, exo = "1 2", "", "c"
        if spec:
            left, _, right = spec.partition("@")
            toks = left.split()
            i = 0
            while i + 1 < len(toks) and toks[i].isdigit() and toks[i + 1].isdigit():
                i += 2
            lags, endo, exo = " ".join(toks[:i]), " ".join(toks[i:]), right.strip()
            if name:
                # show the user's own expressions rather than helper series names
                labels = self.engine.strings(f"{name}.ylab")
                if labels:
                    endo = " ".join(x.lower() for x in labels)
                xl = self.engine.strings(f"{name}.xlab")
                if xl or "c" in exo.split():
                    exo = " ".join((["c"] if "c" in exo.split() else []) + [x.lower() for x in xl])
        e_endo, e_lags, e_exo = QPlainTextEdit(endo), QLineEdit(lags), QLineEdit(exo)
        e_endo.setFont(MONO)
        e_endo.setFixedHeight(70)
        wf = self.engine.wf
        smp = QLineEdit(f"{wf.sample_first} {wf.sample_last}")
        vtype = QComboBox()
        vtype.addItems(["Unrestricted VAR", "Vector Error Correction"])
        vtype.setCurrentIndex(1 if vec else 0)
        trend = QComboBox()
        trend.addItems(["a: no intercept or trend", "b: intercept (no trend) in CE",
                        "c: intercept in CE and VAR", "d: intercept and trend in CE",
                        "e: intercept and trend in CE, linear trend in VAR"])
        trend.setCurrentIndex(2)
        rank = QLineEdit("1")
        if vec and name:
            cs = "".join(self.engine.run(f'printf "%s|%d\\n", {name}.case, {name}.rank')).strip().split("|")
            if len(cs) == 2:
                trend.setCurrentIndex("abcde".index(cs[0]))
                rank.setText(cs[1])
        d = _form_dialog(self, "VAR Specification", [
            ("VAR type:", vtype),
            ("Endogenous variables:", e_endo), ("Lag intervals (in differences for VEC):", e_lags),
            ("Exogenous variables:", e_exo), ("Estimation sample:", smp),
            ("VEC trend case:", trend), ("VEC number of cointegrating equations:", rank)])
        if not d or not e_endo.toPlainText().split():
            return
        is_vec = vtype.currentIndex() == 1
        if name is None:
            k = 1
            while f"var{k:02d}" in wf.bundles:
                k += 1
            name = f"var{k:02d}"
        if smp.text().strip() != f"{wf.sample_first} {wf.sample_last}":
            self.execute("smpl " + self.eviews_dates(smp.text().strip()))
        s = f"{e_lags.text().strip()} {' '.join(e_endo.toPlainText().split())}"
        if e_exo.text().strip():
            s += " @ " + e_exo.text().strip()
        if is_vec:
            exo_part = s.split("@", 1)[1].split() if "@" in s else []
            s = s.split("@")[0].strip()
            exo_rest = [x for x in exo_part if x.lower() != "c"]
            if exo_rest:
                s += " @ " + " ".join(exo_rest)
            self.execute(f"var {name}.ec({trend.currentText()[0]}, {rank.text().strip() or 1}) {s}")
        else:
            self.execute(f"var {name}.ls {s}")
        if name in self.engine.wf.bundles:
            self.open_object((name, self.engine.wf.kinds.get(name, "var")))

    def new_system(self):
        name, ok = QInputDialog.getText(self, "New Object", "Name for the system:", text=self._next_name("sys"))
        if ok and name.strip():
            self.add_window(name.strip(), SystemWindow(self, name.strip()), (720, 560), "system")

    def new_model(self):
        name, ok = QInputDialog.getText(self, "New Object", "Name for the model:", text=self._next_name("model"))
        if ok and name.strip():
            self.add_window(name.strip(), ModelWindow(self, name.strip()), (680, 560), "model")

    def _next_name(self, prefix):
        k = 1
        while f"{prefix}{k:02d}" in self.engine.wf.bundles or f"{prefix}{k:02d}" in self.windows:
            k += 1
        return f"{prefix}{k:02d}"

    def closeEvent(self, e):
        if not self.maybe_save():
            e.ignore()
            return
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
