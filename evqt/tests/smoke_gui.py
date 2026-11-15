"""Off-screen smoke test: drive the main window like a user and save screenshots.

Run:  QT_QPA_PLATFORM=offscreen ~/.venvs/eviews-gretl/bin/python tests/smoke_gui.py OUTDIR
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

from evqt.app import STYLE, light_palette, SystemWindow, ModelWindow, EquationWindow, GroupWindow, MainWindow, SeriesWindow  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "data", "usmacro.gdt")
out = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(out, exist_ok=True)

errors = []
failures = []
QMessageBox.warning = lambda *a, **k: errors.append(a[2] if len(a) > 2 else a)
QMessageBox.question = lambda *a, **k: QMessageBox.Discard     # no modal prompts in the test
QMessageBox.information = lambda *a, **k: None

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
r2_eq = float("".join(w.engine.run('printf "%.10g\\n", eq_cons.rsq')))
check(abs(float(wf.scalars.get("r2", "nan")) - r2_eq) < 1e-5, "scalar from equation member")

eqw = w.windows["eq_untitled1"]
txt = eqw.text.toPlainText()
check("Dependent Variable: DLOG(INV)" in txt and "HAC standard errors" in txt, "equation window shows EViews-style HAC output")

w.open_object(("eq_cons", "equation"))
eqc = w.windows["eq_cons"]
check("Included observations: 140" in eqc.text.toPlainText(), "eq_cons uses 140 obs (dlog of a lag uses pre-sample data)")
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

# --- forecast of a transformed dependent, in levels and as the expression
w.execute("smpl 1985q1 2015q4")
w.execute("equation eqg.ls dlog(cons) c dlog(cons(-1)) dlog(gdp)")
w.execute("smpl 2016q1 2019q4")
dep, base = w.engine.dep_info("eqg")
check(dep == "DLOG(CONS)" and base == "CONS", "forecast dialog offers CONS and DLOG(CONS)")
text, png = w.engine.forecast("eqg", "consf", "", True, True)
check("Forecast: CONSF" in text, "level forecast of CONS from a dlog equation")
vals = w.engine.series_values(["consf", "CONS"])[1]
check(abs(float(vals[0][1]) / float(vals[0][2]) - 1) < 0.02, "level forecast is close to actual CONS at the first step")
text, png = w.engine.forecast("eqg", "dconsf", "", True, False)
check("Forecast: DLOG(CONS)F" in text, "forecast of the expression itself")

# --- explicit equation and ARMA through the command window
w.execute("smpl 1985q1 2015q4")
w.execute("equation eqn.ls cons = c(1)*gdp^c(2)")
check(w.engine.wf.kinds.get("eqn") == "equation", "explicit c(i) equation estimated (NLS)")
w.open_object(("eqn", "equation"))
check("Gauss-Newton" in w.windows["eqn"].text.toPlainText(), "NLS output in the equation window")
w.execute("equation eqa.ls dlog(gdp) c dlog(cons) ar(1) ma(1)")
w.open_object(("eqa", "equation"))
check("Inverted AR Roots" in w.windows["eqa"].text.toPlainText(), "ARMA output with inverted roots")

# --- system window
w.execute("smpl 1985q1 2019q4")
w.new_system.__func__
sysw = SystemWindow(w, "sys1")
w.add_window("sys1", sysw, (700, 500), "system")
sysw.spec.setPlainText("dlog(cons) = c(1) + c(2)*dlog(gdp)\ndlog(inv) = c(3) + c(2)*dlog(gdp) + c(4)*ffr")
from PySide6.QtWidgets import QInputDialog
QInputDialog.getItem = staticmethod(lambda *a, **k: ("Seemingly Unrelated Regression", True))
sysw.estimate()
check(w.engine.wf.kinds.get("sys1") == "system", "System window estimates a SUR system")
check("Seemingly Unrelated Regression" in sysw.text.toPlainText() and "C(4)" in sysw.text.toPlainText(),
      "system output with shared coefficient (4 coefficients)")

# --- FIML and GMM through the system window
sysf = SystemWindow(w, "sysf")
w.add_window("sysf", sysf, (700, 500), "system")
sysf.spec.setPlainText("dlog(cons) = c(1) + c(2)*dlog(gdp) + c(3)*ffr(-1)\ndlog(gdp) = c(4) + c(5)*dlog(cons) + c(6)*ffr")
QInputDialog.getItem = staticmethod(lambda *a, **k: ("Full Information Maximum Likelihood", True))
sysf.estimate()
check("Full Information Maximum Likelihood" in sysf.text.toPlainText(), "FIML system from the system window")
sysg = SystemWindow(w, "sysg")
w.add_window("sysg", sysg, (700, 500), "system")
sysg.spec.setPlainText("dlog(cons) = c(1) + c(2)*dlog(gdp)\ninst ffr(-1) dlog(gdp(-1)) dlog(cons(-1))")
QInputDialog.getItem = staticmethod(lambda *a, **k: ("Generalized Method of Moments (White weighting)", True))
sysg.estimate()
check("J-statistic" in sysg.text.toPlainText(), "GMM system with J-statistic")

# --- structural VAR on the VAR object
w.engine.run("matrix ev_A = {1, 0, 0; NA, 1, 0; NA, NA, 1}\nmatrix ev_B = {NA, 0, 0; 0, NA, 0; 0, 0, NA}")
sv_out = w.engine.run("ev_svar(&v1, ev_A, ev_B)")
check(any("Structural VAR Estimates" in x for x in sv_out), "structural VAR (A-B) on a VAR object")
irf_txt = "\n".join(w.engine.run("ev_varirf(v1, 4)"))
check("Structural decomposition" in irf_txt, "impulse responses use the structural shocks")

# --- model window: equations plus an identity, dynamic solution
w.execute("smpl full")
w.execute("series oth = gdp - cons - inv")
w.execute("smpl 1985q1 2015q4")
w.execute("equation eqmc.ls dlog(cons) c dlog(cons(-1)) dlog(gdp)")
w.execute("equation eqmi.ls dlog(inv) c dlog(inv(-1)) ffr")
w.execute("smpl 2010q1 2019q4")
mw = ModelWindow(w, "mod1")
w.add_window("mod1", mw, (680, 560), "model")
for i in range(mw.eqlist.count()):
    if mw.eqlist.item(i).text() in ("eqmc", "eqmi"):
        mw.eqlist.item(i).setCheckState(Qt.Checked)
mw.ids.setPlainText("gdp = cons + inv + oth")
QInputDialog.getItem = staticmethod(lambda *a, **k: ("Dynamic solution", True))
mw.solve()
check("GDP_0" in w.engine.wf.series and "CONS_0" in w.engine.wf.series, "model solution series *_0 created")
check("Converged" in mw.text.toPlainText(), "model converged")
check(w.engine.wf.kinds.get("mod1") == "model", "model object in the workfile")

# --- HAC GMM, text structural restrictions, model options
w.execute("smpl 1985q1 2019q4")
sysh = SystemWindow(w, "sysh")
w.add_window("sysh", sysh, (700, 500), "system")
sysh.spec.setPlainText("dlog(cons) = c(1) + c(2)*dlog(gdp)\ninst ffr(-1) dlog(gdp(-1)) dlog(cons(-1))")
QInputDialog.getItem = staticmethod(lambda *a, **k: ("Generalized Method of Moments (HAC weighting)", True))
sysh.estimate()
check("HAC (Bartlett kernel" in sysh.text.toPlainText(), "GMM with HAC weighting from the system window")
import evprg2hansl as trm
cmds = trm.svar_text_commands("v1", ["@e1 = c(1)*@u1", "@e2 = c(2)*@e1 + c(3)*@u2", "@e3 = c(4)*@e1 + c(5)*@e2 + c(6)*@u3"], 3)
sv = w.engine.run("\n".join(cmds))
check(any("Structural VAR Estimates" in x for x in sv), "structural VAR from EViews text restrictions")
w.execute("smpl 2010q1 2019q4")
mw.addf.setChecked(False)
mw.init_addfactors()
check("CONS_a" in w.engine.wf.series and mw.addf.isChecked(), "add factors initialised from the model window")
QInputDialog.getItem = staticmethod(lambda *a, **k: ("Static solution", True))
mw.solve()
diff = w.engine.run('eval max(abs(GDP_0 - GDP))')
check(float([x for x in diff if x.strip()][-1]) < 1e-4, "static solution with add factors reproduces GDP")
w.execute("series oth_1 = oth + 100")
mw.ovr.setText("oth")
mw.suffix.setText("_1")
mw.reps.setValue(20)
QInputDialog.getItem = staticmethod(lambda *a, **k: ("Dynamic solution", True))
mw.solve()
check("GDP_1" in w.engine.wf.series and "GDP_1s" in w.engine.wf.series, "scenario with stochastic simulation: GDP_1, GDP_1m, GDP_1s")
check("Scenario: overrides OTH" in mw.text.toPlainText(), "scenario reported in the model window")

# --- VEC through the VAR dialog path (command) and its views
w.execute("smpl 1960q1 2019q4")
w.execute("series lc = log(cons)")
w.execute("series lg = log(gdp)")
w.execute("var vec1.ec(c, 1) 1 2 lc lg")
check(w.engine.wf.kinds.get("vec1") == "vecm", "VEC object")
w.open_object(("vec1", "vecm"))
check("Vector Error Correction Estimates" in w.windows["vec1"].text.toPlainText(), "VEC window output")

# --- save with unsaved-change tracking, and fetch from a data file
check(w.engine.wf.dirty, "workfile marked as changed")
outp = os.path.join(w.engine.tmpdir, "saved.gdt")
written = w.engine.save(outp)
check(os.path.exists(outp) and not w.engine.wf.dirty, "Save writes the workfile and clears the change mark")
check(any(x.endswith("_annual.gdt") for x in written), "other pages saved next to it")
w.execute("pageselect annual")
w.fetch_dialog(os.path.abspath(DATA), choose=["INV"])
check("INV" in w.engine.wf.series, "Fetch from a .gdt data file (not a database)")
w.execute("pageselect usmacro")
check("eq_cons" in w.engine.wf.bundles and "v1" in w.engine.wf.bundles, "Fetch from a data file keeps equations and VARs")
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

# --- ARCH family: TARCH / EGARCH through the gig package
w.execute("smpl 1960q1 2019q4")
w.execute("series r = 100*dlog(gdp)")
w.execute("equation eqt.arch(1,1,t) r c")
check("eqt" in w.engine.wf.bundles and w.engine.is_garch("eqt"), "arch(1,1,t) creates a TARCH equation")
w.open_object(("eqt", "equation"))
et = w.windows["eqt"]
check(et.garch and "Variance Equation" in et.text.toPlainText() if hasattr(et, "text") else et.garch,
      "TARCH equation window shows the variance equation")
QInputDialog.getText = staticmethod(lambda *a, **k: ("gvar", True))
et.make("h")
check("gvar" in w.engine.wf.series, "Make GARCH Variance Series")
w.execute("equation eqe.arch(1,1,e) r c")
check("eqe" in w.engine.wf.bundles, "arch(1,1,e) creates an EGARCH equation")

# --- panel page: structure, IPS test and unstack
PANEL = os.path.join(os.path.dirname(__file__), "..", "..", "data", "panel_demo.csv")
w.execute("pagecreate(page=pan) u 90")
w.engine.run(f'clear --dataset\nopen "{os.path.abspath(PANEL)}" --quiet --preserve', check=True)
w.engine.refresh()
w.execute("pagestruct ID @date(YEAR)")
check(w.engine.is_panel(), "pagestruct makes a panel page")
out = w.engine.run("adf 2 LY --c")
check(any("W_tbar" in ln for ln in out), "panel unit root test (IPS) on the panel page")
w.execute("equation epf.ls(cx=f) LY c LY(-1)")
check("epf" in w.engine.wf.bundles and w.engine.eq_kind("epf") == "panel", "ls(cx=f) on a panel page: fixed effects")
w.open_object(("epf", "equation"))
pw = w.windows["epf"]
check("Cross-section fixed" in pw.text.toPlainText(), "panel equation window shows the effects specification")
w.execute('pageunstack(namepat="*_?", page=wide) ID YEAR @ LY')
check(w.engine.wf.page == "wide" and {"LY_11", "LY_12", "LY_13"} <= set(w.engine.wf.series),
      "pageunstack: new page with one series per unit")
check(w.engine.wf.nobs_full == 30, "unstacked page has T = 30 observations")
w.execute("pagestack(page=long) LY_?")
check(w.engine.wf.page == "long" and "LY_" in w.engine.wf.series and w.engine.wf.nobs_full == 90,
      "pagestack: wide page back to a 3 x 30 panel")
check(w.engine.is_panel(), "stacked page is a panel")
w.select_page("usmacro")
check(w.engine.wf.page == "usmacro", "back to the quarterly page")
w.execute("equation egm.arch(1,1,archm=sd) r c")
check("egm" in w.engine.wf.bundles and w.engine.eq_kind("egm") == "garch", "ARCH-M equation (archm=sd)")
out = "".join(w.engine.run('printf "%s\\n", egm.xlab[1]'))
check("@SQRT(GARCH)" in out, "ARCH-M term listed first in the mean equation")

# --- Phase 1 of the gap analysis: estimators, tests, VAR views, tables
from PySide6.QtWidgets import QInputDialog as _QID  # noqa: E402
_QID.getInt = staticmethod(lambda *a, **k: (2, True))
w.execute("smpl 1970q1 2019q4")
w.execute("equation etsls.tsls dlog(cons) c dlog(gdp) @ c ffr(-1) dlog(gdp(-1)) dlog(cons(-1))")
check(w.engine.eq_kind("etsls") == "tsls", "TSLS equation from the command window")
w.open_object(("etsls", "equation"))
check("Two-Stage Least Squares" in w.windows["etsls"].text.toPlainText(), "TSLS window shows the EViews output")
w.execute("series up = dlog(gdp) > 0.0075")
w.execute("equation elog.binary(d=l) up c ffr")
w.open_object(("elog", "equation"))
check("McFadden R-squared" in w.windows["elog"].text.toPlainText(), "logit window (McFadden R2)")
w.execute("smpl 1960q1 2019q4")
w.execute("equation eard.ardl(deplags=4, reglags=4) log(cons) log(gdp)")
w.open_object(("eard", "equation"))
check("Selected Model" in w.windows["eard"].text.toPlainText(), "ARDL window shows the selected model")
w.execute("smpl 1970q1 2019q4")
w.execute("equation eqls.ls dlog(cons) c dlog(gdp) ffr")
w.open_object(("eqls", "equation"))
ew = w.windows["eqls"]
_QID.getItem = staticmethod(lambda *a, **k: ("Breusch-Pagan-Godfrey", True))
ew.hettest()
check("Breusch-Pagan-Godfrey" in ew.text.toPlainText(), "equation view: heteroskedasticity test")
_QID.getText = staticmethod(lambda *a, **k: ("1990q1", True))
ew.chow(0)
check("Chow Breakpoint Test" in ew.text.toPlainText(), "equation view: Chow breakpoint test")
ew.reset()
check("Ramsey RESET" in ew.text.toPlainText(), "equation view: RESET test")
_QID.getItem = staticmethod(lambda *a, **k: ("CUSUM Test", True))
ew.rls()
check(ew.stack.currentWidget() is ew._scroll, "equation view: CUSUM graph")
w.execute("var vtest.ls 1 2 dlog(cons) dlog(gdp) ffr @ c")
w.open_object(("vtest", "var"))
vw2 = w.windows["vtest"]
vw2.var_lm()
check("Serial Correlation LM" in vw2.text.toPlainText(), "VAR view: residual LM test")
vw2.var_view("matrix ev_vroots = ev_varroots(vtest)")
check("Roots of Characteristic Polynomial" in vw2.text.toPlainText(), "VAR view: AR roots")
w.execute("series lcons = log(cons)")
w.execute("series lgdp = log(gdp)")
w.execute("group gcoint lcons lgdp")
w.open_object(("gcoint", "group"))
w.windows["gcoint"].coint("eg")
check("Engle-Granger" in w.windows["gcoint"].text.toPlainText(), "group view: Engle-Granger test")
w.execute("smpl @all")
w.execute("cons.seas(m) cons_sa cons_sf")
check("cons_sa" in w.engine.wf.series, "seasonal adjustment by moving averages")
w.execute('cons.x13(save="d10 d11")')
_low = [x.lower() for x in w.engine.wf.series]
check("cons_d11" in _low and "cons_d10" in _low, "seasonal adjustment by X-13 (x13as)")
w.execute("table(2,2) tab1")
w.execute('tab1(1,1) = "Mean"')
w.execute("tab1(2,1) = @mean(gdp)")
check(w.engine.wf.kinds.get("tab1") == "table", "table object is listed as a table")
w.open_object(("tab1", "table"))
tw = w.windows["tab1"]
check(tw.table.item(0, 0).text() == "Mean" and tw.table.item(1, 0).text() != "", "table window shows the cells")

# --- Phase 2 estimators from the command window
w.execute("smpl 1970q1 2019q4")
w.execute("equation eqq.qreg(quant=0.25) dlog(cons) c dlog(gdp)")
w.open_object(("eqq", "equation"))
check("Quantile Regression" in w.windows["eqq"].text.toPlainText(), "quantile regression window")
w.execute("equation ecr.cointreg(method=dols) log(cons) log(gdp)")
w.open_object(("ecr", "equation"))
check("DOLS" in w.windows["ecr"].text.toPlainText(), "cointegrating regression window (DOLS)")

_QID.getInt = staticmethod(lambda *a, **k: (6, True))
ew.rescorr()
check("Q-Stat" in ew.text.toPlainText(), "equation view: residual correlogram")
ew.run_text("bundle ev_qa = ev_ubreak(eqls)")
check("Quandt-Andrews" in ew.text.toPlainText(), "equation view: Quandt-Andrews")
w.windows["gcoint"].cause()
check("Granger" in w.windows["gcoint"].text.toPlainText(), "group view: Granger causality")
vw2.var_view("bundle ev_w = ev_varwhite(vtest)")
check("Heteroskedasticity" in vw2.text.toPlainText(), "VAR view: White test")

w.close()
print(f"FAILED: {failures}" if failures else "ALL OK")
if failures:
    print("ERRORS:", [str(e)[:300] for e in errors[-6:]])
sys.exit(1 if failures else 0)
