"""evqt: an EViews-style desktop interface on top of gretl."""
import os
import sys

# the .prg translator lives next to this project
_TR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "translator")
if _TR not in sys.path:
    sys.path.insert(0, _TR)
