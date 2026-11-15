"""A persistent gretlcli process that the interface talks to.

Each command is sent over stdin followed by an end marker; output is read back
until the marker appears. gretlcli echoes commands as "? ..." lines (and long
ones over several lines); those echoes are dropped.
"""
from __future__ import annotations

import csv
import os
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field

GRETL_APP = "/Applications/Gretl.app"
GRETLCLI = os.path.join(GRETL_APP, "Contents/Resources/bin/gretlcli")
GRETL_HOME = os.path.join(GRETL_APP, "Contents/Resources/share/gretl/")

_MARK = "__EVQT_END__"


class GretlError(RuntimeError):
    pass


@dataclass
class Workfile:
    path: str | None = None
    nobs_full: int = 0
    first: str = ""
    last: str = ""
    sample_first: str = ""
    sample_last: str = ""
    sample_nobs: int = 0
    pd: int = 1
    series: list = field(default_factory=list)
    bundles: list = field(default_factory=list)
    lists: list = field(default_factory=list)
    scalars: dict = field(default_factory=dict)
    strings: list = field(default_factory=list)


_ERR_PATTERNS = re.compile(
    r"(is undefined|Terminated on error|Data error|Syntax error|Invalid option|"
    r"Error message from|error in function|You can only do this|Couldn't|"
    r"Unknown variable|not a valid|Expected .* but found|Parse error|"
    r"No such file|Error attempting)", re.IGNORECASE)


class GretlEngine:
    def __init__(self, gretlcli: str = GRETLCLI):
        env = dict(os.environ, GRETL_HOME=GRETL_HOME)
        self.tmpdir = tempfile.mkdtemp(prefix="evqt_")
        self.proc = subprocess.Popen(
            [gretlcli], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1, env=env, cwd=self.tmpdir)
        self.lock = threading.Lock()
        self.wf = Workfile()
        self.plot_counter = 0
        self.run("set messages off")
        out = self.run("include EViewsCompat.gfn")
        self.has_compat = not any("rror" in ln for ln in out)

    # -- low level --------------------------------------------------------
    def run(self, commands: str, check: bool = False) -> list[str]:
        """Send one or more hansl lines; return output lines (echo removed)."""
        with self.lock:
            self.proc.stdin.write(commands.rstrip("\n") + f'\nprint "{_MARK}"\n')
            self.proc.stdin.flush()
            out, in_echo = [], False
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    raise GretlError("gretl process ended unexpectedly")
                line = line.rstrip("\n")
                if line == _MARK:
                    break
                if line.startswith("? ") or line.startswith("> "):
                    in_echo = line.endswith("\\")
                    continue
                if in_echo:
                    in_echo = line.endswith("\\")
                    continue
                if line.startswith("Type \"open filename\"") or line.startswith("gretl version") \
                        or line.startswith("Copyright") or line.startswith("This is free software") \
                        or line.startswith("Current session"):
                    continue
                out.append(line)
        if check and self.is_error(out):
            raise GretlError("\n".join(out).strip())
        return out

    @staticmethod
    def is_error(out: list[str]) -> bool:
        return any(_ERR_PATTERNS.search(ln) for ln in out)

    def close(self):
        try:
            self.proc.stdin.write("quit\n\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()

    # -- workfile ---------------------------------------------------------
    def open(self, path: str) -> list[str]:
        out = self.run(f'open "{path}" --quiet --preserve', check=True)
        self.wf = Workfile(path=path)
        info = self._query('printf "%s|%s|%d|%d\\n", obslabel(1), obslabel($nobs), $nobs, $pd')
        self.wf.first, self.wf.last, n, pd = info.split("|")
        self.wf.nobs_full, self.wf.pd = int(n), int(pd)
        self.refresh()
        return out

    def new_workfile(self, freq: str, start: str, end: str) -> None:
        from evprg2hansl import workfile  # translator helper
        self.run("\n".join(workfile(freq, start, end)), check=True)
        self.wf = Workfile(path=None)
        info = self._query('printf "%s|%s|%d|%d\\n", obslabel(1), obslabel($nobs), $nobs, $pd')
        self.wf.first, self.wf.last, n, pd = info.split("|")
        self.wf.nobs_full, self.wf.pd = int(n), int(pd)
        self.refresh()

    def _query(self, cmd: str) -> str:
        out = [ln for ln in self.run(cmd) if ln.strip()]
        if not out or self.is_error(out):
            raise GretlError("\n".join(out))
        return out[-1].strip()

    def refresh(self) -> Workfile:
        """Re-read sample and object lists from gretl."""
        try:
            s = self._query('printf "%s|%s|%d\\n", obslabel($t1), obslabel($t2), $nobs')
            self.wf.sample_first, self.wf.sample_last, n = s.split("|")
            self.wf.sample_nobs = int(n)
        except GretlError:
            return self.wf
        self.wf.series = self._names_from_varlist(self.run("varlist --type=series"))
        self.wf.bundles = self._names_typed(self.run("varlist --type=bundle"))
        self.wf.lists = self._names_typed(self.run("varlist --type=list"))
        self.wf.strings = self._names_typed(self.run("varlist --type=string"))
        self.wf.scalars = {}
        for ln in self.run("varlist --type=scalar"):
            m = re.match(r"\s*(\w+)\s*=\s*(\S+)", ln)
            if m and not m.group(1).startswith("ev_"):
                self.wf.scalars[m.group(1)] = m.group(2)
        self.wf.bundles = [b for b in self.wf.bundles if not b.startswith("ev_")]
        self.wf.lists = [b for b in self.wf.lists if not b.startswith("ev_")]
        return self.wf

    @staticmethod
    def _names_from_varlist(out: list[str]) -> list[str]:
        names = []
        for ln in out:
            names += re.findall(r"\d+\)\s+(\w+)", ln)
        return [n for n in names if n != "const"]

    @staticmethod
    def _names_typed(out: list[str]) -> list[str]:
        return [ln.strip() for ln in out
                if ln.startswith("  ") and re.fullmatch(r"\s+\w+", ln)]

    # -- data access ------------------------------------------------------
    def series_values(self, names: list[str]) -> tuple[list[str], list[list[str]]]:
        """Current-sample values via a temporary CSV."""
        path = os.path.join(self.tmpdir, "view.csv")
        self.run(f'store "{path}" {" ".join(names)}', check=True)
        with open(path, newline="") as f:
            rows = list(csv.reader(f))
        return rows[0], rows[1:]

    def tmp_png(self) -> str:
        self.plot_counter += 1
        return os.path.join(self.tmpdir, f"plot{self.plot_counter:03d}.png")

    def plot(self, cmd_without_output: str) -> str:
        """Run a gnuplot command into a PNG file and return its path."""
        path = self.tmp_png()
        self.run(f'{cmd_without_output} --output="{path}"', check=True)
        if not os.path.exists(path):
            raise GretlError("graph was not produced")
        return path

    def equation_text(self, name: str) -> str:
        return "\n".join(self.run(f"ev_print(&{name})", check=True)).strip("\n")
