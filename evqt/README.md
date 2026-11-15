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

Not yet: Forecast, Fetch/Store (databases), multiple workfile pages, VAR/system
objects, editing cells in the spreadsheet, the explicit `y=c(1)+c(2)*x` form.

## Tests
```bash
cd ~/Desktop/eviews-gretl/evqt
QT_QPA_PLATFORM=offscreen ~/.venvs/eviews-gretl/bin/python tests/smoke_gui.py /tmp/evqt-shots
```

## Known issue
macOS accessibility tools that set a text field's whole value at once can crash
Qt 6.8.1 (seen once while automating the command window). Normal typing is fine.
