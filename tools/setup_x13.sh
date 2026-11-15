#!/bin/sh
# Install the bundled X-13ARIMA-SEATS program (third_party/x13as) and point gretl at it.
#   tools/setup_x13.sh            install to ~/.local/x13as (or $X13_DEST) and update ~/.gretl2rc
#   tools/setup_x13.sh --check    only report the current state
set -eu

here=$(cd "$(dirname "$0")/.." && pwd)
src="$here/third_party/x13as"
dest="${X13_DEST:-$HOME/.local/x13as}"
rc="${GRETL_CONFIG_FILE:-$HOME/.gretl2rc}"

current=""
if [ -f "$rc" ]; then
    current=$(sed -n 's/^x12a *= *//p' "$rc" | head -n 1)
fi

if [ "${1:-}" = "--check" ]; then
    echo "gretl config: $rc"
    echo "x12a (X-13 program) = ${current:-<not set>}"
    if [ -n "$current" ] && [ -x "$current" ]; then
        echo "status: the program exists and is executable"
    else
        echo "status: not installed (run tools/setup_x13.sh)"
    fi
    exit 0
fi

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
    echo "The bundled x13as is built for Apple Silicon Macs only."
    echo "Get a build for your system from https://www.census.gov/data/software/x13as.X-13ARIMA-SEATS.html"
    echo "(or gretl's Linux builds) and set  x12a = /path/to/x13as  in $rc"
    exit 1
fi

# integrity check against the checksums recorded in third_party/x13as/README.md
cd "$src"
cat <<'SUMS' | shasum -a 256 -c --quiet -
b99b94794228d976e46dbf69a9c2b30edb75425c773f89fc31a12cf3f43e22c1  bin/x13as
f3c0153daed38e3b250186f600687f649148d1ecd1b25c58a9f5ed7b5fc36cbb  lib/libgcc_s.1.1.dylib
4871ac9977a1e71554963df41d5e0775c8eb7159b55589bbe03fc6926b866d3e  lib/libgfortran.5.dylib
3510a7a8033ff6657b18b83609e0b80c86abc2066a0ce0ca1c96f0f24b60cbd0  lib/libquadmath.0.dylib
SUMS

# copy bin/ and lib/ side by side (x13as finds the libraries through @rpath)
mkdir -p "$dest/bin" "$dest/lib"
cp -p "$src/bin/x13as" "$dest/bin/x13as"
cp -p "$src"/lib/*.dylib "$dest/lib/"
chmod 755 "$dest/bin/x13as"
xattr -dr com.apple.quarantine "$dest" 2>/dev/null || true

# the program must start
tmp=$(mktemp -d)
if ! (cd "$tmp" && "$dest/bin/x13as" 2>&1 | grep -q "X-13ARIMA-SEATS"); then
    rm -rf "$tmp"
    echo "x13as did not start from $dest" >&2
    exit 1
fi
rm -rf "$tmp"

# gretl configuration: x12a = <program>
prog="$dest/bin/x13as"
if [ -f "$rc" ]; then
    if [ "$current" != "$prog" ]; then
        cp -p "$rc" "$rc.bak-x13"
        if grep -q '^x12a *=' "$rc"; then
            sed -i '' "s|^x12a *=.*|x12a = $prog|" "$rc"
        else
            printf '# Path to x12arima (or x13)\nx12a = %s\n' "$prog" >> "$rc"
        fi
        echo "Updated $rc (backup: $rc.bak-x13)"
    else
        echo "$rc already points to $prog"
    fi
else
    printf '# gretl config file\n# Path to x12arima (or x13)\nx12a = %s\n' "$prog" > "$rc"
    echo "Created $rc"
fi
echo "X-13ARIMA-SEATS installed: $prog"
