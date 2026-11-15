#!/bin/sh
# Start the EViews-style interface for gretl.
#   ./run_evqt.sh [data file | program.prg]
cd "$(dirname "$0")" && exec "$HOME/.venvs/eviews-gretl/bin/python" -m evqt "$@"
