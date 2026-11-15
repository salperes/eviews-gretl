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
  Equation (LS with ordinary/White/HAC covariance, or GARCH(1,1)).
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

Not yet: stochastic simulation and scenarios in models, add factors, nonlinear system
equations, GMM with HAC weighting, structural VAR restrictions written as text (@e1 = ...).

## Tests
```bash
cd ~/Desktop/eviews-gretl/evqt
QT_QPA_PLATFORM=offscreen ~/.venvs/eviews-gretl/bin/python tests/smoke_gui.py /tmp/evqt-shots
```

## Known issue
macOS accessibility tools that set a text field's whole value at once can crash
Qt 6.8.1 (seen once while automating the command window). Normal typing is fine.
