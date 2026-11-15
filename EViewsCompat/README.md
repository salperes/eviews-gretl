# EViewsCompat (gretl package)

EViews-style `ls` (including explicit `c(i)` equations by NLS and ARMA terms), forecasts
(static/dynamic, level forecasts of dlog/d/log dependents, multi-step S.E., evaluation
statistics), systems (LS, WLS, SUR, 2SLS, weighted 2SLS, 3SLS, GMM with shared coefficients;
FIML results through ev_sysfrom), VAR and VEC objects (estimates, Granger tests, Johansen
test, structural A-B and long-run identification, impulse responses, variance
decomposition, lag length criteria), model solution (equations plus identities, Newton),
Wald test, residual diagnostics, freeze and @-functions for gretl.
Usage: see `EViewsCompat_help.txt` and `EViewsCompat_sample.inp`.

## Build / test / install

The gretlcli in Gretl.app has a wrong built-in data path, so set GRETL_HOME first:

```bash
export GRETL_HOME=/Applications/Gretl.app/Contents/Resources/share/gretl/
```

```bash
for t in test_evcompat test_usmacro test_forecast_var test_estimators test_systems test_advanced; do /Applications/Gretl.app/Contents/Resources/bin/gretlcli -b "$PWD/tests/$t.inp" | grep -E '^(ok|FAIL)'; done
```

```bash
/Applications/Gretl.app/Contents/Resources/bin/gretlcli -b "$PWD/build.inp"
```

Install (what works with the gretl 2026d macOS build): put `EViewsCompat.gfn` in a
subfolder `functions/EViewsCompat/` under both `~/.gretl/` and
`~/Library/Application Support/gretl/`, plus a `functions/packages.xml` in each with
`path="/menubar/Model/LinearModels"` (gretl did not save the menu registration itself).

GUI: gretl string fields hold at most 31 characters, so the dialog has three
equation fields that are joined with spaces.

## hansl gotchas found while writing this
- Functions end with `end function`; `data`, `lags`, `labels` are reserved words.
- Functions cannot widen the sample or write outside it, and a series made inside a
  function has only in-sample values; pass dataset series (list members) to `var`
  so lags can use pre-sample data.
- `{}` cannot be assigned to a variable named like a command; matrix minus row
  vector needs `.-`.
- In interactive gretlcli, `open` asks before replacing data: run `clear --dataset` first.
- Dataset series are not visible inside functions: pass them as a list (`dataset`).
- The at-sign is string substitution, so the source never writes it literally.
- `catch` must not wrap calls to user-defined functions.
- Files in `$dotdir` (~/.gretl) are deleted when gretl exits.
