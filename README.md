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
- PySide6 6.12 for `evqt` (`evqt/requirements.txt`), in a virtual environment outside any
  cloud-synced folder.

On macOS the bundled `gretlcli` needs `GRETL_HOME` set:
```bash
export GRETL_HOME=/Applications/Gretl.app/Contents/Resources/share/gretl/
```

## Quick start
```bash
# 1. build and install the gretl package (add --evqt for the interface, --test to run the tests)
tools/install.sh --evqt

# 2. translate an EViews program
python3 translator/evprg2hansl.py translator/examples/usmacro.prg

# 3. start the EViews-style interface
python -m evqt data/usmacro.gdt        # from the evqt/ folder
```
Each folder's README has details, tests and the list of what is not done yet.
Step-by-step installation for automated agents (and anyone installing from git):
[AGENTS.md](AGENTS.md).

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

## Optional: Census X-13ARIMA-SEATS

`x.x13` (and evqt's *Seasonal Adjustment: Census X-13*) use gretl's `deseas()`, which needs the
`x13as` program. A build for Apple Silicon Macs is bundled in
[`third_party/x13as`](third_party/x13as) (public domain program, GCC run-time libraries; see its
README for origin, checksums and licences). Install it once:

```bash
tools/setup_x13.sh
```

The script checks the files, copies them to `~/.local/x13as`, tests that the program starts and
sets `x12a = ~/.local/x13as/bin/x13as` in `~/.gretl2rc` (keeping a backup). `tools/setup_x13.sh
--check` shows the current setting. On other systems, install a Census Bureau build and set
`x12a` yourself.
