# Instructions for agents: installing eviews-gretl from git

This file is for automated agents (and people) that clone this repository and set it up. Follow the
steps in order; every command is non-interactive. Report the output of the verification step to the
user.

## What gets installed

| Part | Where it goes | Needed for |
|---|---|---|
| `EViewsCompat` gretl package (built from `EViewsCompat/EViewsCompat.inp`) | gretl's user function folder (`$dotdir/functions`, usually `~/.gretl/functions`; on macOS also `~/Library/Application Support/gretl/functions` for the gretl app) | everything |
| `translator/evprg2hansl.py` | stays in the checkout (Python standard library only) | translating EViews `.prg` files |
| `evqt` desktop interface | a Python virtual environment with PySide6 (default `~/.venvs/eviews-gretl`) | the EViews-style GUI (optional) |
| X-13ARIMA-SEATS (`third_party/x13as`) | `~/.local/x13as`, plus `x12a = ...` in `~/.gretl2rc` | `x.x13` seasonal adjustment (optional, Apple Silicon Macs) |

## Prerequisites (check them, do not install system software without asking the user)

1. **gretl 2026a or newer.** Check with `gretlcli --version`, or on macOS
   `/Applications/Gretl.app/Contents/Resources/bin/gretlcli --version`.
   - macOS: the official signed `.pkg` from https://gretl.sourceforge.net (installs `/Applications/Gretl.app`).
   - Linux: the distribution package (`apt-get install gretl`) is often older than 2026a; then build
     from source or use the gretl site's packages. Ask the user before using `sudo`.
   - Windows: not supported by the scripts here (use WSL with a Linux gretl).
   The packages EViewsCompat uses (`gig`, `regls`, `ivpanel`, `dbnomics`) ship with gretl.
2. **Python 3.10+.** The script uses the first one that runs among `$PYTHON`, `python3.14` ...
   `python3.10`, Homebrew's and `python3`. On macOS `/usr/bin/python3` may be Apple's stub that only
   asks to install the Xcode tools; Homebrew's Python (`/opt/homebrew/bin/python3`) works.
3. **Network access** only for `pip` (PySide6, about 117 MB) when installing evqt. Ask the user first if
   downloads need approval in your environment.

## Install

```bash
git clone https://github.com/salperes/eviews-gretl.git
cd eviews-gretl
tools/install.sh --evqt --test
```

Options: no option = package and translator only; `--evqt` adds the GUI environment; `--x13` installs
the bundled X-13 program (Apple Silicon Macs; it edits `~/.gretl2rc` and keeps a backup, so ask the
user first); `--test` runs all test suites; `--all` = everything. Useful variables: `GRETLCLI`,
`GRETL_HOME`, `EVQT_VENV`, `PYTHON` (see the top of `tools/install.sh`).

The script stops with `ERROR: ...` and a reason when something is missing. It is safe to run again.

### Expected result

The last lines are `== Done`. With `--test` you should see, before that:

```
package: 4xx checks ok, 0 failures
OK                      (translator unit tests)
ok: evqt smoke test
```

Package tests take a few minutes (several use simulation). Any `FAIL` line is a real failure: report it
with the test file name.

## Using it

```bash
# translate an EViews program (output: program.inp next to it)
python3 translator/evprg2hansl.py --case upper translator/examples/usmacro.prg

# run the translated script (on macOS set GRETL_HOME first, see below)
gretlcli -b translator/examples/usmacro.inp

# start the EViews-style interface
cd evqt && ~/.venvs/eviews-gretl/bin/python -m evqt ../data/usmacro.gdt
```

In gretl scripts load the package with `include EViewsCompat.gfn`.

## Platform notes

- **macOS:** the bundled `gretlcli` needs
  `export GRETL_HOME=/Applications/Gretl.app/Contents/Resources/share/gretl/`
  (the install script and evqt set it themselves).
- **Virtual environment location:** keep it outside cloud-synced folders (Desktop, Documents, iCloud,
  Dropbox, OneDrive). Qt plugins inside synced folders fail to load.
- **Qt version:** use PySide6 6.12 (`evqt/requirements.txt`). Qt 6.8.1 crashes on macOS when
  accessibility tools write into evqt's command window.
- **Headless machines:** evqt tests run with `QT_QPA_PLATFORM=offscreen` (the script does this).
- **evqt and gretlcli:** evqt starts `gretlcli` from `$EVQT_GRETLCLI`, else the macOS app, else the
  `PATH`.

## Manual installation (if the script cannot be used)

```bash
cd EViewsCompat
gretlcli -b "$PWD/build.inp"                     # writes EViewsCompat.gfn
printf 'install "%s/EViewsCompat.gfn" --local\n' "$PWD" > /tmp/inst.inp
gretlcli -b /tmp/inst.inp                       # prints "Installed EViewsCompat.gfn"
cd ../evqt
python3 -m venv ~/.venvs/eviews-gretl
~/.venvs/eviews-gretl/bin/pip install -r requirements.txt
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `The symbol 'ev_...' is undefined` | The installed package is older than the source: rerun `tools/install.sh`. |
| `gretlcli` prints errors about `/home/cottrell/...` or finds no data (macOS) | `GRETL_HOME` is not set (see Platform notes). |
| `gretl ... is too old` | Install gretl 2026a or newer. |
| evqt: `Could not find the Qt platform plugin "cocoa"` | The venv is in a cloud-synced folder: recreate it elsewhere with `EVQT_VENV=...`. |
| evqt crashes while an automation tool types into it | Qt 6.8 is installed: `pip install -r evqt/requirements.txt` (6.12). |
| `no working Python 3.10+ found`, or the Xcode licence message | Install Python 3.10+ (e.g. Homebrew) or set `PYTHON=/path/to/python3`. |
| `x.x13` reports that x13as is missing | Run `tools/setup_x13.sh` (Apple Silicon) or set `x12a = /path/to/x13as` in `~/.gretl2rc`. |

## For agents changing the code

- Run the tests above after a change; after editing `EViewsCompat/EViewsCompat.inp` rebuild and
  reinstall (`tools/install.sh`), otherwise gretl keeps using the old package.
- New public package functions go into the `public =` list of `EViewsCompat/EViewsCompat.spec`.
- The feature backlog with the status of every EViews feature is `docs/GAP_ANALIZI.md` (Turkish).
- Do not commit `translator/real_prg/` (third-party programs without a licence), `screenshots/`, or
  files with personal paths; `.gitignore` covers them.
