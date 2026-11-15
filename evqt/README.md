# evqt: EViews-style interface for gretl

A desktop window laid out like EViews (command window, workfile window, object
windows with View/Proc/Object/Name/Freeze/Estimate/Stats/Resids buttons).
All computation is done by gretl, through a persistent `gretlcli` process and the
EViewsCompat package. EViews commands typed in the command window are translated by
`../translator/evprg2hansl.py`; anything it does not recognise is passed to gretl as is.

## Start
```bash
./run_evqt.sh ../data/usmacro.gdt        # from this folder
```
With no argument it starts empty (File > Open, or File > New Workfile). A `.prg`
argument runs that EViews program.

Needs: gretl in /Applications, the EViewsCompat package installed, and the Python
environment at `~/.venvs/eviews-gretl` (PySide6 6.8.1). The environment is kept out
of iCloud-synced folders on purpose.

## What works
- Command window: Enter runs the line under the cursor (`smpl`, `series`, `genr`,
  `group`, `ls`, `equation x.ls(cov=hac)`, `x.wald`, `x.line`, `scalar` ...).
  Object names are case-insensitive, as in EViews.
- Workfile window: Range/Sample, object icons (series, group, equation, scalar,
  string), Details+/-, double-click to open, right-click to rename/delete.
- Series: spreadsheet, line graph, histogram, statistics + Jarque-Bera,
  correlogram, ADF test, HP filter.
- Group: spreadsheet, line graph, scatter with fit line, statistics, correlations.
- Equation: EViews-style output, Actual/Fitted/Residual graph, residual
  diagnostics, Wald test, make residual/fitted series, re-estimate.
- Quick menu: Sample, Generate Series, Show, Graph, Series Statistics, Estimate
  Equation (LS with ordinary/White/HAC covariance, or ARCH: GARCH, TARCH or EGARCH with
  ARCH and GARCH orders, threshold order and an ARCH-M term; the ARCH equation window
  shows the variance equation, a
  conditional variance graph and Make GARCH Variance Series).
- File: open gdt/csv/xlsx/dta/wf1..., save as .gdt, run EViews programs.
- Freeze saves the current view to a file (txt, csv or png).

- Forecast button: series to forecast (for dlog(Y), d(Y), log(Y) equations: Y itself, as in
  EViews, or the expression), forecast and S.E. names, dynamic/static, forecast sample;
  graph with +/- 2 S.E. bands and the evaluation table (RMSE, MAE, MAPE, Theil, proportions).
  Dynamic forecasts recompute every regressor that uses the forecast series; their S.E.
  follow the lags of the dependent variable (and the ARMA terms).
- Equations: `y c x`, explicit `y = c(1) + c(2)*x^c(3)` (NLS), ARMA terms `ar(1) ma(1)`
  (regression with ARMA errors, exact ML, with inverted roots).
- VAR and VEC objects: Quick > Estimate VAR (type, lags, trend case, rank) or
  `var v1.ls ...` / `var v1.ec(c, 1) ...`; output with coefficient, (s.e.), [t]; Granger
  tests; lag length criteria; Johansen cointegration test; impulse responses; variance
  decomposition; residual graphs and series.
- Systems: Quick > Estimate System, or `system s1` + `s1.append ...` + `s1.sur`; equations
  linear in c(i), shared coefficients across equations, `inst` lines; LS, WLS, SUR, 2SLS,
  weighted 2SLS, 3SLS, FIML (gretl's system estimator) and two-step GMM (White weighting,
  J-statistic).
- Structural VAR: VAR window > Proc > Estimate Structural Factorization: A-B pattern
  matrices (NA = estimated, ML with LR over-identification test) or long-run
  (Blanchard-Quah) restrictions; impulse responses and variance decomposition then use
  the structural shocks.
- Models: Quick > Make Model: tick estimated equations, write identities, Solve (dynamic or
  static, Newton). Solutions are saved as `<name>_0` series, with actual-vs-solution graphs.
- Fetch / Store: gretl databases (`.bin`); Fetch also reads any data file gretl opens
  (`.wf1`, `.gdt`, `.csv`, `.xlsx`, `.dta` ...). EViews `.edb` databases use a closed format
  and cannot be read: save the series to a `.wf1` workfile in EViews and fetch from that.
- Workfile pages: tabs at the bottom of the workfile window, New Page (any frequency or a
  copy), right-click to rename or delete; each page keeps its sample, groups and objects.
- Edit+/- in series and group spreadsheets.
- Unsaved changes: `*` in the titles; Save (Cmd+S) writes the current page to its .gdt
  and other pages next to it as `<name>_<page>.gdt`; closing or opening another file asks first.

Also: nonlinear system equations (estimated with Levenberg-Marquardt), GMM with HAC
(Newey-West) weighting, structural VAR restrictions in EViews text form (`@e1 = c(1)*@u1`,
`@lr1(@u2) = 0`), and in the Model window: scenario overrides with a solution suffix,
add factors (and initialising them so the equations fit), stochastic simulation
(mean and standard deviation series).

Phase 3: the equation dialog has all estimation methods of the package (PARCH and component
ARCH among the ARCH models); VAR dialog: Bayesian VAR; VAR window > Proc > Cointegration
Restrictions (VEC); group view: Factor Analysis; series view: seasonal graph. Workfile window:
Copy / Paste objects (Cmd+C / Cmd+V; another page receives series with frequency conversion),
spreadsheet cells copy as tab-separated text, File > Print prints the active output, table or
graph.

Panel pages: workfile Proc > Structure/Resize Current Page (cross-section id and date
series) or `pagestruct id @date(t)`; Proc > Reshape Current Page: Unstack in New Page or
`pageunstack(namepat="*_?", page=wide) id t @ x` makes one series per unit. On a panel
page `x.uroot(ips)` gives the Im-Pesaran-Shin test. EViews programs run from File may use
subroutines, `include` files and matrix algebra (see the translator README).

On a panel page the equation dialog adds cross-section effects (none, fixed, random) and
period fixed effects. Proc > Reshape Current Page: Stack in New Page (or
`pagestack(page=long) x_?`) turns one-series-per-unit data into a panel page.

Not yet: period random effects, EViews-specific add-ins.

Known issue: Qt 6.8 on macOS can crash when accessibility automation tools drive the
window in the background; normal mouse and keyboard use is not affected.

## Tests
```bash
cd ~/Desktop/eviews-gretl/evqt
QT_QPA_PLATFORM=offscreen ~/.venvs/eviews-gretl/bin/python tests/smoke_gui.py /tmp/evqt-shots
```

## Known issue
macOS accessibility tools that set a text field's whole value at once can crash
Qt 6.8.1 (seen once while automating the command window). Normal typing is fine.
