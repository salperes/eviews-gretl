#!/bin/sh
# Install eviews-gretl from a git checkout: build and install the EViewsCompat gretl package,
# optionally set up the evqt interface (Python venv with PySide6), X-13, and run the tests.
#
#   tools/install.sh                 build + install EViewsCompat, check that gretl loads it
#   tools/install.sh --evqt          also create the evqt virtual environment
#   tools/install.sh --x13           also install the bundled X-13 program (Apple Silicon Macs)
#   tools/install.sh --test          also run the test suites (needs --evqt for the GUI test)
#   tools/install.sh --all           all of the above
#
# Environment variables:
#   GRETLCLI    path to gretlcli (default: macOS app bundle, else gretlcli on the PATH)
#   GRETL_HOME  gretl's share directory (set automatically for the macOS app bundle)
#   EVQT_VENV   virtual environment for evqt (default: ~/.venvs/eviews-gretl)
#   PYTHON      Python 3.10+ used to create the venv and run the translator (default: python3)
#
# Non-interactive; safe to run again (it rebuilds and reinstalls).
set -eu

repo=$(cd "$(dirname "$0")/.." && pwd)
want_evqt=0; want_x13=0; want_test=0
for a in "$@"; do
    case "$a" in
        --evqt) want_evqt=1 ;;
        --x13) want_x13=1 ;;
        --test) want_test=1 ;;
        --all) want_evqt=1; want_x13=1; want_test=1 ;;
        -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
        *) echo "unknown option: $a" >&2; exit 2 ;;
    esac
done

step() { printf '\n== %s\n' "$1"; }
die() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

# --- 1. gretl ---------------------------------------------------------------------------
step "Locating gretl"
mac_app=/Applications/Gretl.app
if [ -z "${GRETLCLI:-}" ]; then
    if [ -x "$mac_app/Contents/Resources/bin/gretlcli" ]; then
        GRETLCLI="$mac_app/Contents/Resources/bin/gretlcli"
    elif command -v gretlcli >/dev/null 2>&1; then
        GRETLCLI=$(command -v gretlcli)
    else
        die "gretlcli not found. Install gretl 2026a or newer (https://gretl.sourceforge.net):
  macOS: the official .pkg from the gretl site (installs /Applications/Gretl.app)
  Debian/Ubuntu: sudo apt-get install gretl   (check that the version is 2026a or newer)
then run this script again, or set GRETLCLI=/path/to/gretlcli."
    fi
fi
case "$GRETLCLI" in
    "$mac_app"/*) export GRETL_HOME="${GRETL_HOME:-$mac_app/Contents/Resources/share/gretl/}" ;;
esac
export GRETLCLI
echo "gretlcli: $GRETLCLI"
[ -n "${GRETL_HOME:-}" ] && echo "GRETL_HOME: $GRETL_HOME"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
run_hansl() {  # run a hansl snippet from stdin, print gretl's output without command echoes
    cat > "$tmp/s.inp"
    "$GRETLCLI" -b "$tmp/s.inp" 2>&1 | grep -v '^?' || true
}
ver=$(printf 'printf "VER=%%d\\n", $version\n' | run_hansl | sed -n 's/^VER=//p')
[ -n "$ver" ] || die "gretlcli did not run (on macOS check GRETL_HOME)"
echo "gretl version code: $ver"
[ "$ver" -ge 20260 ] || die "gretl $ver is too old: 2026a (20260) or newer is needed"

# --- 2. EViewsCompat package ------------------------------------------------------------
step "Building EViewsCompat.gfn"
cd "$repo/EViewsCompat"
out=$("$GRETLCLI" -b "$repo/EViewsCompat/build.inp" 2>&1 || true)
if printf '%s\n' "$out" | grep -q -i -E 'error|halting'; then
    printf '%s\n' "$out" | tail -15
    die "package build failed"
fi
[ -s EViewsCompat.gfn ] || die "EViewsCompat.gfn was not written"
echo "built $(ls -l EViewsCompat.gfn | awk '{print $5}') bytes"

step "Installing EViewsCompat for gretl"
res=$(printf 'install "%s/EViewsCompat/EViewsCompat.gfn" --local\nprintf "DOT=%%s\\n", $dotdir\n' "$repo" | run_hansl)
printf '%s\n' "$res" | grep -q "Installed EViewsCompat" || { printf '%s\n' "$res"; die "gretl could not install the package"; }
echo "installed into $(printf '%s\n' "$res" | sed -n 's/^DOT=//p')functions (used by gretlcli and evqt)"
if [ "$(uname -s)" = "Darwin" ]; then
    # the gretl GUI app on macOS reads packages from Application Support
    gui="$HOME/Library/Application Support/gretl/functions/EViewsCompat"
    mkdir -p "$gui"
    cp EViewsCompat.gfn "$gui/"
    echo "also copied to $gui (gretl GUI app)"
fi

step "Checking that gretl loads the package"
chk=$(printf 'nulldata 10\ninclude EViewsCompat.gfn\nseries t = ev_trend()\nprintf "CHECK=%%g\\n", t[10]\n' | run_hansl)
printf '%s\n' "$chk" | grep -q '^CHECK=9$' || { printf '%s\n' "$chk" | tail -8; die "the package does not load"; }
echo "ok: EViewsCompat works"

# --- 3. translator (standard library only) ------------------------------------------------
step "Checking the translator"
PYTHON=${PYTHON:-python3}
command -v "$PYTHON" >/dev/null 2>&1 || die "$PYTHON not found (Python 3.10+ is needed)"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || die "$PYTHON is older than 3.10"
"$PYTHON" "$repo/translator/evprg2hansl.py" --help >/dev/null || die "the translator does not start"
echo "ok: $("$PYTHON" --version) runs translator/evprg2hansl.py"

# --- 4. evqt ------------------------------------------------------------------------------
venv=${EVQT_VENV:-$HOME/.venvs/eviews-gretl}
if [ "$want_evqt" = 1 ]; then
    step "Setting up evqt in $venv"
    case "$venv" in
        "$HOME/Desktop"*|"$HOME/Documents"*|*"Mobile Documents"*|*iCloud*|*Dropbox*|*OneDrive*)
            echo "WARNING: $venv may be in a cloud-synced folder; Qt plugins can break there." >&2 ;;
    esac
    [ -x "$venv/bin/python" ] || "$PYTHON" -m venv "$venv"
    "$venv/bin/python" -m pip install -q --upgrade pip
    "$venv/bin/python" -m pip install -q -r "$repo/evqt/requirements.txt"
    "$venv/bin/python" -c 'import PySide6.QtCore as q, PySide6.QtWidgets, PySide6.QtPrintSupport; print("ok: Qt", q.qVersion())'
    echo "start with:  cd \"$repo/evqt\" && \"$venv/bin/python\" -m evqt ../data/usmacro.gdt"
fi

# --- 5. X-13 ------------------------------------------------------------------------------
if [ "$want_x13" = 1 ]; then
    step "Installing X-13ARIMA-SEATS"
    if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
        "$repo/tools/setup_x13.sh"
    else
        echo "skipped: the bundled x13as is for Apple Silicon Macs; see the README to set x12a yourself"
    fi
fi

# --- 6. tests -----------------------------------------------------------------------------
if [ "$want_test" = 1 ]; then
    step "Package tests (EViewsCompat/tests, a few minutes)"
    fails=0; oks=0
    for t in "$repo"/EViewsCompat/tests/*.inp; do
        o=$(cd "$repo/EViewsCompat/tests" && "$GRETLCLI" -b "$t" 2>&1 || true)
        k=$(printf '%s\n' "$o" | grep -c -E '^[[:space:]]*(ok|PASS)\b' || true)
        f=$(printf '%s\n' "$o" | grep -c -E '^[[:space:]]*FAIL|\*\*\* error' || true)
        oks=$((oks + k)); fails=$((fails + f))
        [ "$f" -gt 0 ] && echo "  failures in $(basename "$t")" && printf '%s\n' "$o" | grep -E 'FAIL|\*\*\* error' | head -5
    done
    echo "package: $oks checks ok, $fails failures"

    step "Translator unit tests"
    (cd "$repo/translator" && "$PYTHON" -m unittest -q test_evprg2hansl) || fails=$((fails + 1))

    if [ -x "$venv/bin/python" ]; then
        step "evqt off-screen test"
        shots="$tmp/shots"
        if (cd "$repo/evqt" && QT_QPA_PLATFORM=offscreen "$venv/bin/python" tests/smoke_gui.py "$shots" 2>/dev/null | tail -1 | grep -q "ALL OK"); then
            echo "ok: evqt smoke test"
        else
            echo "evqt smoke test FAILED (run it by hand to see the checks)"; fails=$((fails + 1))
        fi
    else
        echo "(evqt test skipped: no venv; use --evqt)"
    fi
    [ "$fails" -eq 0 ] || die "$fails test failure(s)"
fi

step "Done"
echo "EViewsCompat is installed. Translate a program with:"
echo "  $PYTHON \"$repo/translator/evprg2hansl.py\" --case upper program.prg"
