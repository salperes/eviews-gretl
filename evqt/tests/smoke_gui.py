"""Off-screen smoke test: drive the main window like a user and save screenshots.

Run:  QT_QPA_PLATFORM=offscreen ~/.venvs/eviews-gretl/bin/python tests/smoke_gui.py OUTDIR
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from evqt.app import STYLE, light_palette, EquationWindow, GroupWindow, MainWindow, SeriesWindow  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "data", "usmacro.gdt")
out = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(out, exist_ok=True)

errors = []
failures = []
QMessageBox.warning = lambda *a, **k: errors.append(a[2] if len(a) > 2 else a)

app = QApplication([])
app.setStyle("Fusion")
app.setPalette(light_palette())
app.setStyleSheet(STYLE)
w = MainWindow()
w.resize(1300, 860)
w.show()


def check(cond, what):
    print(("ok    " if cond else "FAIL  ") + what)
    if not cond:
        failures.append(what)


w.open_file(os.path.abspath(DATA))
wf = w.engine.wf
check(wf.nobs_full == 319 and "GDP" in wf.series, "open usmacro.gdt")
check(w.wf_window.list.count() == 5, "workfile window lists 5 series")

# EViews commands typed in the command window
for cmd in ["smpl 1985q1 2019q4",
            "series dlc = dlog(CONS)",
            "genr infl = @pcy(CPI)",
            "group macro GDP CONS INV",
            "equation eq_cons.ls dlog(CONS) c dlog(GDP) dlog(CONS(-1)) FFR",
            "scalar r2 = eq_cons.rsq",
            "ls(cov=hac) dlog(INV) c dlog(GDP) FFR"]:
    w.execute(cmd)
    app.processEvents()

wf = w.engine.wf
check(wf.sample_first == "1985:1" and wf.sample_last == "2019:4", "smpl sets the sample (1985:1-2019:4)")
check("dlc" in wf.series and "infl" in wf.series, "series/genr create series")
check("macro" in wf.lists, "group creates a list")
check("eq_cons" in wf.bundles, "equation object created")
check("eq_untitled1" in wf.bundles, "bare ls creates an untitled equation")
check(isinstance(w.windows.get("eq_untitled1"), EquationWindow), "bare ls opens an equation window")
check(abs(float(wf.scalars.get("r2", "nan")) - 0.4066216899) < 1e-6, "scalar from equation member")

eqw = w.windows["eq_untitled1"]
txt = eqw.text.toPlainText()
check("Dependent Variable: DLOG(INV)" in txt and "HAC standard errors" in txt, "equation window shows EViews-style HAC output")

w.open_object(("eq_cons", "equation"))
eqc = w.windows["eq_cons"]
check("Included observations: 139" in eqc.text.toPlainText(), "eq_cons uses 139 obs (pre-sample lag used)")
eqc.afr()
check(eqc.stack.currentWidget() is eqc._scroll and not eqc.image.original().isNull(), "Actual/Fitted/Residual graph")
eqc.diag()
check("Breusch-Godfrey" in eqc.text.toPlainText(), "residual diagnostics view")
eqc.output()

w.open_object(("GDP", "series"))
sw = w.windows["GDP"]
check(isinstance(sw, SeriesWindow) and sw.table.rowCount() == 140, "series spreadsheet shows 140 sample obs")

w.open_object(("macro", "group"))
gw = w.windows["macro"]
check(isinstance(gw, GroupWindow) and gw.table.columnCount() == 3, "group spreadsheet has 3 columns")
check(gw.members() == ["GDP", "CONS", "INV"], "group members")

w.execute("gdp.line")      # EViews graph command, lower-case name -> graph window
check(any(k.startswith("Graph:") for k in w.windows), "series.line opens a graph window")

w.execute("NOPE = 1 + undefined_thing")
check(len(errors) >= 1, "errors are reported to the user")
errors.clear()

# --- cell editing (Edit+/-)
sw.toggle_edit()
orig = sw.table.item(0, 0).text()
sw.table.item(0, 0).setText("99999")
app.processEvents()
check(w.engine.series_values(["GDP"])[1][0][1] == "99999", "Edit+/- writes an edited cell to gretl")
sw.table.item(0, 0).setText(orig)
check(w.engine.series_values(["GDP"])[1][0][1] == orig, "edited cell restored")
errors_before = len(errors)
sw.table.item(1, 0).setText("abc")
app.processEvents()
check(len(errors) == errors_before + 1, "non-numeric cell is refused")
sw.toggle_edit()

# --- forecast: button path (engine + window) and command path
w.execute("smpl 1985q1 2015q4")
w.execute("equation eqf.ls ffr c ffr(-1) dlog(gdp)")
w.execute("smpl 2016q1 2019q4")
text, png = w.engine.forecast("eqf", "ffrf", "ffrse", True)
w.forecast_window("Forecast: ffrf", text, png)
check("ffrf" in w.engine.wf.series and "ffrse" in w.engine.wf.series, "Forecast creates forecast and S.E. series")
check("Theil Inequality Coef." in text, "forecast evaluation table")
w.execute("eqf.fit ffr_static")
check("ffr_static" in w.engine.wf.series, "eq.fit command (static forecast)")

# --- VAR
w.execute("smpl 1985q1 2019q4")
w.execute("var v1.ls 1 2 dlog(cons) dlog(gdp) ffr @ c")
check(w.engine.wf.kinds.get("v1") == "var", "var command creates a VAR object")
w.open_object(("v1", "var"))
vw = w.windows["v1"]
vt = vw.text.toPlainText()
check("Vector Autoregression Estimates" in vt and "Included observations: 140" in vt,
      "VAR window: EViews-style output on 140 obs (pre-sample lags used)")
vw.granger()
check("Block Exogeneity" in vw.text.toPlainText(), "VAR Granger causality view")
vw.decomp.__func__  # exists
w.engine.run("set horizon 10")
path = w.engine.tmp_png()
w.engine.run(f'ev_varirfplot(v1, 10, "{path}")', check=True)
vw.show_image(path)
check(not vw.image.original().isNull(), "VAR impulse response grid")
w.execute("v1.makeresids rc rg rf")
check("rf" in w.engine.wf.series, "VAR makeresids")
items = [w.wf_window.list.item(i).data(0x0100) for i in range(w.wf_window.list.count())]
check(("v1", "var") in items and ("eqf_fc", "bundle") not in items, "workfile shows VAR, hides helper bundles")

# --- Store / Fetch and pages
dbp = os.path.join(w.engine.tmpdir, "test.bin")
w.store_dialog(["GDP", "FFR"], path=dbp)
check([c[0] for c in w.engine.db_contents(dbp)] == ["GDP", "FFR"], "Store writes series to a database")
w.execute("pagecreate(page=annual) a 1990 2019")
check(w.engine.wf.page == "annual" and w.engine.wf.pd == 1, "pagecreate makes an annual page")
check(w.wf_window.tabs.count() == 3, "page tabs: usmacro, annual, New Page")
w.fetch_dialog(dbp, choose=["GDP"])
check("GDP" in w.engine.wf.series and w.engine.wf.nobs_full == 30, "Fetch brings GDP into the annual page")
w.execute("pageselect usmacro")
check(w.engine.wf.page == "usmacro" and "CONS" in w.engine.wf.series, "pageselect returns to the quarterly page")
check("v1" in w.engine.wf.bundles and w.engine.wf.sample_first == "1985:1", "objects and sample kept per page")
w.open_object(("eq_cons", "equation"))
eqc = w.windows["eq_cons"]
w.open_object(("GDP", "series"))
sw = w.windows["GDP"]
w.open_object(("macro", "group"))
gw = w.windows["macro"]
w.open_object(("v1", "var"))
vw = w.windows["v1"]

# lay out windows like a user would and take a screenshot
subs = {s.widget(): s for s in w.mdi.subWindowList()}
for s in w.mdi.subWindowList():
    s.hide()
for widget, geo in [(w.wf_window, (8, 8, 560, 330)), (vw, (576, 8, 700, 470)),
                    (sw, (8, 346, 420, 300)), (gw, (436, 486, 520, 200))]:
    s = subs[widget]
    s.setGeometry(*geo)
    s.show()
vw.parentWidget().raise_()
w.command.setPlainText("smpl 1985q1 2019q4\nequation eq_cons.ls dlog(CONS) c dlog(GDP) dlog(CONS(-1)) FFR\n")
app.processEvents()
shot = os.path.join(out, "evqt_main.png")
w.grab().save(shot)
check(os.path.getsize(shot) > 10000, f"screenshot saved: {shot}")

eqc.afr()
app.processEvents()
eqc.parentWidget().grab().save(os.path.join(out, "evqt_afr.png"))

w.close()
print(f"FAILED: {failures}" if failures else "ALL OK")
sys.exit(1 if failures else 0)
