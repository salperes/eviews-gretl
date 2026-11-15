# EViewsCompat (gretl package)

EViews-style `ls`, Wald test, residual diagnostics, freeze and @-functions for gretl.
Usage: see `EViewsCompat_help.txt` and `EViewsCompat_sample.inp`.

## Build / test / install

The gretlcli in Gretl.app has a wrong built-in data path, so set GRETL_HOME first:

```bash
export GRETL_HOME=/Applications/Gretl.app/Contents/Resources/share/gretl/
```

```bash
/Applications/Gretl.app/Contents/Resources/bin/gretlcli -b "$PWD/tests/test_evcompat.inp" | grep -E '^(ok|FAIL)'
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
- Functions end with `end function`; `data`, `lags` are reserved words.
- Dataset series are not visible inside functions: pass them as a list (`dataset`).
- The at-sign is string substitution, so the source never writes it literally.
- `catch` must not wrap calls to user-defined functions.
- Files in `$dotdir` (~/.gretl) are deleted when gretl exits.
