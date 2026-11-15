# eviews-gretl

EViews-style econometrics on top of [gretl](https://gretl.sourceforge.net), the free
and open-source econometrics package. Three parts:

| Folder | What it is |
|---|---|
| [`EViewsCompat/`](EViewsCompat) | A gretl function package: EViews-style least squares output, Wald tests in `c(i)` notation, residual diagnostics, Freeze, and the `@`-functions (`@pch`, `@trend`, `@seas`, `@movav` ...). Adds *Model › Linear models › EViews-style equation (LS)* to gretl's menus. |
| [`translator/`](translator) | `evprg2hansl.py`: translates EViews programs (`.prg`) into gretl scripts (`.inp`). |
| [`evqt/`](evqt) | A desktop interface laid out like EViews (command window, workfile window, series / group / equation windows) that drives gretl in the background. |
| [`data/`](data) | `usmacro.gdt`, a quarterly US macro dataset built from FRED, used by the examples and tests. |

Results are checked against gretl's own commands (coefficients, standard errors,
information criteria, Wald, Breusch-Godfrey, White, Jarque-Bera, HAC/White covariance).

## Requirements
- macOS or Linux with gretl 2026a or newer (developed on gretl 2026d, Apple Silicon).
- Python 3.10+ for the translator (standard library only).
- PySide6 for `evqt` (`pip install PySide6==6.8.1`, preferably in a virtual
  environment outside any cloud-synced folder).

On macOS the bundled `gretlcli` needs `GRETL_HOME` set:
```bash
export GRETL_HOME=/Applications/Gretl.app/Contents/Resources/share/gretl/
```

## Quick start
```bash
# 1. build and install the gretl package
cd EViewsCompat && gretlcli -b "$PWD/build.inp"
# then in gretl: File › Function packages › On local machine › install EViewsCompat.gfn

# 2. translate an EViews program
python3 translator/evprg2hansl.py translator/examples/usmacro.prg

# 3. start the EViews-style interface
python -m evqt data/usmacro.gdt        # from the evqt/ folder
```
Each folder's README has details, tests and the list of what is not done yet.

## Not affiliated
This project is not affiliated with or endorsed by EViews or S&P Global. "EViews" is
a trademark of its owner and is used here only to describe compatibility. No EViews
code, documentation or files are included.

## Licence
GPL-3.0, the same licence as gretl. See [LICENSE](LICENSE).

---

**Türkçe özet:** gretl üzerinde EViews benzeri çalışma ortamı. `EViewsCompat` gretl'e
EViews tarzı tahmin, test ve fonksiyonlar ekler; `translator` EViews `.prg`
programlarını gretl betiğine çevirir; `evqt` EViews düzeninde bir masaüstü arayüzüdür.
