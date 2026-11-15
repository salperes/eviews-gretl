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

- Forecast button: forecast name, S.E. series, dynamic/static, forecast sample;
  opens a window with the forecast and +/- 2 S.E. bands and the evaluation table
  (RMSE, MAE, MAPE, Theil, bias/variance/covariance proportions).
- VAR objects: Quick > Estimate VAR (or `var v1.ls 1 2 y1 y2 @ c x`); output with
  coefficient, (s.e.), [t]; Granger / block exogeneity tests; lag length criteria;
  impulse responses (grid of graphs); variance decomposition; residual graphs and series.
- Fetch / Store: gretl databases (`.bin`). Store writes the selected series (whole range);
  Fetch lists a database and imports the chosen series, converting frequency by averaging.
- Workfile pages: tabs at the bottom of the workfile window, New Page (annual, quarterly,
  monthly, daily, undated, or a copy), right-click to rename or delete;
  `pagecreate`/`pageselect`/`pagedelete` in the command window. Each page keeps its own
  sample, groups, equations and VARs.
- Edit+/- in series and group spreadsheets: edited cells are written straight to gretl
  (the data file on disk changes only when you save).

Not yet: the explicit `y=c(1)+c(2)*x` form, ARMA terms, system objects (SUR, 2SLS
systems), VEC models, structural VAR restrictions, EViews `.edb` databases (gretl
`.bin` databases are used instead). Dynamic forecasts use lags of a plain dependent
variable only, and their S.E. is the one-step formula.

## Tests
```bash
cd ~/Desktop/eviews-gretl/evqt
QT_QPA_PLATFORM=offscreen ~/.venvs/eviews-gretl/bin/python tests/smoke_gui.py /tmp/evqt-shots
```

## Known issue
macOS accessibility tools that set a text field's whole value at once can crash
Qt 6.8.1 (seen once while automating the command window). Normal typing is fine.
