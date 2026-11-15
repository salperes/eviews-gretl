# X-13ARIMA-SEATS for gretl (macOS, Apple Silicon)

`bin/x13as` is the U.S. Census Bureau's X-13ARIMA-SEATS seasonal adjustment program
(version 1.1, build 60), compiled for arm64 macOS. `lib/` holds the GNU Fortran run-time
libraries it needs (found through `@rpath`, so keep `bin/` and `lib/` side by side).

Install with `tools/setup_x13.sh` (copies the program to `~/.local/x13as` and points gretl's
configuration at it). Then `x.x13` in EViews programs and *Seasonal Adjustment: Census X-13*
in evqt work through gretl's `deseas()`.

## Origin

Unpacked unchanged from `x13as-mac-arm64.tar.gz` (dated 2023-07-23, SHA-256
`3ff141a43f94e5f88bed30b7fa68d4fb644ec4b25f2fd7a29d5e3bd513848ad4`), published by the gretl
project at <https://sourceforge.net/projects/gretl/files/x13as/>.

| File | SHA-256 |
|---|---|
| bin/x13as | b99b94794228d976e46dbf69a9c2b30edb75425c773f89fc31a12cf3f43e22c1 |
| lib/libgcc_s.1.1.dylib | f3c0153daed38e3b250186f600687f649148d1ecd1b25c58a9f5ed7b5fc36cbb |
| lib/libgfortran.5.dylib | 4871ac9977a1e71554963df41d5e0775c8eb7159b55589bbe03fc6926b866d3e |
| lib/libquadmath.0.dylib | 3510a7a8033ff6657b18b83609e0b80c86abc2066a0ce0ca1c96f0f24b60cbd0 |

## Licences

- **X-13ARIMA-SEATS** was written by U.S. Government employees and is not subject to
  copyright in the United States (public domain). Program and documentation:
  <https://www.census.gov/data/software/x13as.X-13ARIMA-SEATS.html>
- **libgfortran, libquadmath, libgcc_s** are part of GCC and are distributed under the
  GNU General Public License version 3 with the GCC Runtime Library Exception
  (<https://www.gnu.org/licenses/gcc-exception-3.1.html>), which permits redistributing them
  with programs compiled by GCC. Their source code is available from <https://gcc.gnu.org/>.

## Other systems

The Census Bureau publishes Windows and Linux builds and the Fortran source code (build with
`gfortran`); gretl publishes builds for Linux. Install one of them and set
`x12a = /path/to/x13as` in `~/.gretl2rc`.
