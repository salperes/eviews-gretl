"""A persistent gretlcli process that the interface talks to.

Each command is sent over stdin followed by an end marker; output is read back
until the marker appears. gretlcli echoes commands as "? ..." lines (and long
ones over several lines); those echoes are dropped.
"""
from __future__ import annotations

import csv
import os
import queue
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field

import shutil

# gretlcli: $EVQT_GRETLCLI, else the macOS app bundle, else gretlcli on the PATH (Linux packages).
# The macOS bundle's gretlcli needs GRETL_HOME; elsewhere it is taken from the environment if set.
GRETL_APP = "/Applications/Gretl.app"
_MAC_CLI = os.path.join(GRETL_APP, "Contents/Resources/bin/gretlcli")
GRETLCLI = os.environ.get("EVQT_GRETLCLI") or (_MAC_CLI if os.path.exists(_MAC_CLI) else (shutil.which("gretlcli") or _MAC_CLI))
GRETL_HOME = os.environ.get("GRETL_HOME") or (
    os.path.join(GRETL_APP, "Contents/Resources/share/gretl/") if GRETLCLI == _MAC_CLI else "")

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
    kinds: dict = field(default_factory=dict)       # bundle -> "equation" | "var" | "vecm" | "system" | "bundle"
    dirty: bool = False                             # unsaved changes
    # workfile pages: each page is a dataset kept as a .gdtb file while not shown
    page: str = "page1"
    pages: list = field(default_factory=lambda: ["page1"])
    obj_page: dict = field(default_factory=dict)    # equation/VAR name -> page
    page_lists: dict = field(default_factory=dict)  # page -> {list name: members}
    page_sample: dict = field(default_factory=dict) # page -> (first, last)


_ERR_PATTERNS = re.compile(
    r"(is undefined|Terminated on error|Data error|Syntax error|Invalid option|"
    r"Error message from|error in function|You can only do this|Couldn't|"
    r"Unknown variable|not a valid|Expected .* but found|Parse error|"
    r"No such file|Error attempting)", re.IGNORECASE)


EQ_KINDS = {"ls", "nls", "arma", "garch", "panel", "tsls", "binary", "ardl", "mlreg", "cointreg", "dpanel",
            "robustls", "breakls", "threshold", "switchreg", "glm", "enet", "heckit", "midas", "paneliv",
            "panelre2", "logl", "sspace"}


class GretlEngine:
    def __init__(self, gretlcli: str = GRETLCLI):
        env = dict(os.environ, GRETL_HOME=GRETL_HOME) if GRETL_HOME else dict(os.environ)
        self.tmpdir = tempfile.mkdtemp(prefix="evqt_")
        self.proc = subprocess.Popen(
            [gretlcli], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1, env=env, cwd=self.tmpdir)
        self.lock = threading.Lock()
        self._lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self.wf = Workfile()
        self.plot_counter = 0
        self.run("set messages off")
        out = self.run("include EViewsCompat.gfn")
        self.has_compat = not any("rror" in ln for ln in out)

    # -- low level --------------------------------------------------------
    def _reader(self):
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def run(self, commands: str, check: bool = False, timeout: float = 120) -> list[str]:
        """Send one or more hansl lines; return output lines (echo removed).

        If gretl does not finish within `timeout` seconds (for example because it
        is waiting at a question), an empty answer is sent and GretlError raised.
        """
        with self.lock:
            self.proc.stdin.write(commands.rstrip("\n") + f'\nprint "{_MARK}"\n')
            self.proc.stdin.flush()
            out, in_echo = [], False
            while True:
                try:
                    line = self._lines.get(timeout=timeout)
                except queue.Empty:
                    self.proc.stdin.write("\n")
                    self.proc.stdin.flush()
                    raise GretlError(f"gretl did not answer within {timeout:.0f} s")
                if line is None:
                    raise GretlError("gretl process ended unexpectedly")
                line = line.rstrip("\n")
                if line == _MARK:
                    break
                if line.startswith("? ") or line.startswith("> ") or line.startswith("<"):
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
        out = self.run(f'clear --dataset\nopen "{path}" --quiet --preserve', check=True)
        page = re.sub(r"\W", "_", os.path.splitext(os.path.basename(path))[0].lower()) or "page1"
        self.wf = Workfile(path=path, page=page, pages=[page])
        self._read_range()
        self.refresh()
        return out

    def _read_range(self):
        info = self._query('printf "%s|%s|%d|%d\\n", obslabel(1), obslabel($nobs), $nobs, $pd')
        self.wf.first, self.wf.last, n, pd = info.split("|")
        self.wf.nobs_full, self.wf.pd = int(n), int(pd)

    def new_workfile(self, freq: str, start: str, end: str) -> None:
        from evprg2hansl import workfile  # translator helper
        self.run("\n".join(workfile(freq, start, end)), check=True)
        self.wf = Workfile(path=None)
        self._read_range()
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
        self.wf.series = [n for n in self._names_from_varlist(self.run("varlist --type=series"))
                          if not n.startswith("ev_")]
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
        new = [b for b in self.wf.bundles if b not in self.wf.kinds]
        if new:
            q = "\n".join(f'printf "%s|%d|%d|%s\\n", "{b}", inbundle({b}, "sys"), inbundle({b}, "uhat"), '
                          f'inbundle({b}, "kind") ? {b}.kind : ""' for b in new)
            for ln in self.run(q):
                parts = ln.strip().split("|")
                if len(parts) == 4:
                    b, sys_, uh, kind = parts
                    if kind in ("vecm", "system", "model", "table"):
                        self.wf.kinds[b] = kind
                    elif kind in EQ_KINDS:
                        self.wf.kinds[b] = "equation"
                    else:
                        self.wf.kinds[b] = "var" if sys_ != "0" else ("equation" if uh != "0" else "bundle")
        for b in self.wf.bundles:
            self.wf.obj_page.setdefault(b, self.wf.page)
        for gone in [b for b in self.wf.kinds if b not in self.wf.bundles]:
            self.wf.kinds.pop(gone)
            self.wf.obj_page.pop(gone, None)
        return self.wf

    # -- pages --------------------------------------------------------------
    def _page_file(self, name: str) -> str:
        return os.path.join(self.tmpdir, f"page_{name}.gdtb")

    def _save_page(self):
        wf = self.wf
        lists = {}
        for L in wf.lists:
            out = "".join(self.run(f'printf "%s\\n", varname({L})')).strip()
            lists[L] = [x for x in out.split(",") if x]
        wf.page_lists[wf.page] = lists
        wf.page_sample[wf.page] = (wf.sample_first, wf.sample_last)
        self.run(f'smpl full\nstore "{self._page_file(wf.page)}"', check=True)

    def _enter_page(self, name: str):
        wf = self.wf
        wf.page = name
        self._read_range()
        for L, members in wf.page_lists.get(name, {}).items():
            if members:
                self.run(f"list {L} = {' '.join(members)}")
        smp = wf.page_sample.get(name)
        if smp and smp[0]:
            self.run(f"smpl {smp[0]} {smp[1]}")
        self.refresh()

    def new_page(self, name: str, freq: str, start: str = "", end: str = ""):
        from evprg2hansl import workfile
        if name in self.wf.pages:
            raise GretlError(f"page {name} already exists")
        self._save_page()
        if freq == "u":
            cmds = [f"nulldata {int(end)} --preserve"]
        elif freq == "copy":
            cmds = []                       # the saved file of the current page is reopened below
        else:
            cmds = [c + (" --preserve" if c.startswith("nulldata") else "") for c in workfile(freq, start, end)]
        if freq == "copy":
            self.run(f'clear --dataset\nopen "{self._page_file(self.wf.page)}" --quiet --preserve', check=True)
        else:
            self.run("\n".join(cmds), check=True)
        self.wf.pages.append(name)
        self.wf.page_lists[name] = {}
        self._enter_page(name)

    def select_page(self, name: str):
        if name == self.wf.page:
            return
        if name not in self.wf.pages:
            raise GretlError(f"no page called {name}")
        self._save_page()
        self.run(f'clear --dataset\nopen "{self._page_file(name)}" --quiet --preserve', check=True)
        self._enter_page(name)

    def delete_page(self, name: str):
        if len(self.wf.pages) == 1:
            raise GretlError("a workfile needs at least one page")
        if name == self.wf.page:
            other = next(p for p in self.wf.pages if p != name)
            self.select_page(other)
        self.wf.pages.remove(name)
        for b in [b for b, p in self.wf.obj_page.items() if p == name]:
            self.run(f"catch delete {b}")
        try:
            os.remove(self._page_file(name))
        except OSError:
            pass
        self.refresh()

    def rename_page(self, old: str, new: str):
        if new in self.wf.pages or not re.fullmatch(r"[A-Za-z]\w*", new):
            raise GretlError(f"cannot use {new!r} as a page name")
        wf = self.wf
        wf.pages[wf.pages.index(old)] = new
        for b, p in wf.obj_page.items():
            if p == old:
                wf.obj_page[b] = new
        for d in (wf.page_lists, wf.page_sample):
            if old in d:
                d[new] = d.pop(old)
        if os.path.exists(self._page_file(old)):
            os.replace(self._page_file(old), self._page_file(new))
        if wf.page == old:
            wf.page = new

    # -- databases (gretl .bin format) ----------------------------------------
    @staticmethod
    def db_contents(path: str) -> list[tuple[str, str, str]]:
        """(name, description, frequency and range) for each series in a .bin database."""
        idx = os.path.splitext(path)[0] + ".idx"
        out = []
        with open(idx, encoding="utf-8", errors="replace") as f:
            lines = [ln.rstrip("\n") for ln in f if not ln.startswith("#")]
        for i in range(0, len(lines) - 1, 2):
            name, _, desc = lines[i].partition("  ")
            out.append((name.strip(), desc.strip(), lines[i + 1].strip()))
        return out

    def db_store(self, path: str, names: list[str]):
        """Store whole series (like EViews), whatever the current sample."""
        self.run(f'scalar ev_s1 = $t1\nscalar ev_s2 = $t2\nsmpl full\n'
                 f'store "{path}" {" ".join(names)} --database --overwrite\nsmpl ev_s1 ev_s2', check=True)

    def db_fetch(self, path: str, names: list[str]):
        if not path.endswith(".bin"):
            path = self.file_as_db(path)
        self.run(f'open "{path}" --quiet\ndata {" ".join(names)} --quiet', check=True)
        self.wf.dirty = True
        self.refresh()

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
    def series_values(self, names: list[str], with_obs: bool = False):
        """Current-sample values via a temporary CSV. With with_obs, also the
        observation numbers (1-based, whole workfile) of the rows."""
        path = os.path.join(self.tmpdir, "view.csv")
        extra = ""
        if with_obs:
            self.run("series ev_obsno = obs")
            extra = " ev_obsno"
        self.run(f'store "{path}" {" ".join(names)}{extra}', check=True)
        with open(path, newline="") as f:
            rows = list(csv.reader(f))
        if not with_obs:
            return rows[0], rows[1:]
        obsno = [int(float(r[-1])) for r in rows[1:]]
        return rows[0][:-1], [r[:-1] for r in rows[1:]], obsno

    def set_value(self, name: str, obsno: int, value: str):
        v = value.strip()
        if v.upper() in ("", "NA", "NAN"):
            v = "NA"
        else:
            float(v)                       # raises ValueError for non-numbers
        self.run(f"{name}[{obsno}] = {v}", check=True)
        self.wf.dirty = True

    def forecast(self, eq: str, fname: str, sename: str, dynamic: bool, level: bool = True) -> tuple[str, str]:
        """EViews Forecast: series fname (and sename), evaluation text and graph.
        With level, a transformed dependent (dlog(Y)...) is forecast as Y."""
        self.run(f"bundle ev_fc = ev_forecast({eq}, dataset, {int(dynamic)}, 1, {int(level)})", check=True)
        cmds = [f"series {fname} = ev_fcast_series(ev_fc, ev_fc.level)"]
        if sename:
            cmds.append(f"series {sename} = ev_fcast_se(ev_fc, ev_fc.level)")
        self.run("\n".join(cmds), check=True)
        text = "\n".join(self.run("ev_fprint(&ev_fc)", check=True)).strip("\n")
        png = self.tmp_png()
        self.run(f'ev_fplot(&ev_fc, "{png}")', check=True)
        self.wf.dirty = True
        self.refresh()
        return text, png

    def dep_info(self, eq: str) -> tuple[str, str]:
        """(dependent expression, base series) of an equation; base is '' when the
        dependent is not log/d/dlog of a single series."""
        out = self.run(f'printf "%s|%s\\n", {eq}.depvar, ev_depbase({eq}, dataset)')
        for ln in out:
            parts = ln.strip().split("|")
            if len(parts) == 2:
                return parts[0], parts[1]
        return "", ""

    # -- saving -------------------------------------------------------------
    def save(self, path: str | None = None) -> list[str]:
        """Save the workfile: the current page to path, other pages next to it
        as <name>_<page>.gdt. Returns the files written."""
        wf = self.wf
        path = path or wf.path
        if not path or not path.endswith((".gdt", ".gdtb")):
            raise GretlError("choose a .gdt file name with Save As")
        self.run(f'scalar ev_s1 = $t1\nscalar ev_s2 = $t2\nsmpl full\nstore "{path}"\nsmpl ev_s1 ev_s2', check=True)
        written = [path]
        others = [p for p in wf.pages if p != wf.page]
        if others:
            base = os.path.splitext(path)[0]
            cur = wf.page
            self._save_page()
            try:
                for p in others:
                    target = f"{base}_{p}.gdt"
                    self.run(f'clear --dataset\nopen "{self._page_file(p)}" --quiet --preserve\n'
                             f'store "{target}"', check=True)
                    written.append(target)
            finally:
                self.run(f'clear --dataset\nopen "{self._page_file(cur)}" --quiet --preserve')
                self._enter_page(cur)
        wf.path = path
        wf.dirty = False
        return written

    # -- fetch from any data file -----------------------------------------
    def file_as_db(self, path: str) -> str:
        """Convert a data file gretl can read (.wf1, .gdt, .csv, .xlsx, .dta ...)
        into a temporary .bin database, keeping the current workfile as it is."""
        db = os.path.join(self.tmpdir, "fetch_" + re.sub(r"\W", "_", os.path.basename(path)) + ".bin")
        if os.path.exists(db) and os.path.getmtime(db) >= os.path.getmtime(path):
            return db
        self._save_page()
        try:
            # --preserve: opening the file must not delete equations, VARs and other objects
            self.run(f'clear --dataset\nopen "{path}" --quiet --preserve', check=True)
            self.run(f'store "{db}" --database --overwrite', check=True)
        finally:
            self.run(f'clear --dataset\nopen "{self._page_file(self.wf.page)}" --quiet --preserve')
            self._enter_page(self.wf.page)
        return db

    def tmp_png(self) -> str:
        self.plot_counter += 1
        return os.path.join(self.tmpdir, f"plot{self.plot_counter:03d}.png")

    def plot(self, cmd_without_output: str, settings: list | None = None) -> str:
        """Run a gnuplot command into a PNG file and return its path (settings: gnuplot 'set' lines)."""
        path = self.tmp_png()
        block = (" { " + "; ".join(settings) + "; }") if settings else ""
        self.run(f'{cmd_without_output} --output="{path}"{block}', check=True)
        if not os.path.exists(path):
            raise GretlError("graph was not produced")
        return path

    def strings(self, expr: str) -> list[str]:
        """Elements of a gretl array of strings."""
        out = self.run(f"eval {expr}")
        return [m.group(1) for ln in out for m in [re.match(r'\[\d+\] "(.*)"$', ln.strip())] if m]

    def eq_kind(self, name: str) -> str:
        """kind member of an equation bundle (ls, nls, garch, panel ...)."""
        out = self.run(f'string ev_k = "ls"\nif inbundle({name}, "kind")\nev_k = {name}.kind\nendif\n'
                       f'printf "%s\\n", ev_k')
        lines = [x.strip() for x in out if x.strip()]
        return lines[-1] if lines else "ls"

    def table_cells(self, name: str) -> list[list[str]]:
        """Cells of an EViewsCompat table object, row by row."""
        out = self.run(f'loop ev_i = 1..{name}.rows\nloop ev_j = 1..{name}.cols\n'
                       f'printf "%s\\t", ev_tget({name}, ev_i, ev_j)\nendloop\nprintf "\\n"\nendloop')
        rows = [ln.rstrip("\n").split("\t")[:-1] for ln in out if "\t" in ln]
        return rows

    def is_garch(self, name: str) -> bool:
        # nested ifs: hansl's ?: evaluates both branches
        out = self.run(f'scalar ev_g = 0\nif inbundle({name}, "kind")\nif {name}.kind == "garch"\n'
                       f'ev_g = 1\nendif\nendif\nprintf "%d\\n", ev_g')
        return "".join(out).strip().endswith("1")

    def equation_text(self, name: str) -> str:
        fn = {"garch": "ev_garchprint", "panel": "ev_panelprint", "binary": "ev_binaryprint",
              "ardl": "ev_ardlprint", "mlreg": "ev_mlprint"}.get(self.eq_kind(name), "ev_print")
        if self.eq_kind(name) in EQ_KINDS - {"ls", "nls", "arma", "garch", "panel", "tsls", "binary", "ardl", "mlreg"}:
            fn = "ev_coefprint"
        return "\n".join(self.run(f"{fn}(&{name})", check=True)).strip("\n")

    # -- panel pages --------------------------------------------------------
    def is_panel(self) -> bool:
        return self._query('printf "%d\\n", $datatype') == "3"

    def set_panel(self, unit: str, time: str):
        """EViews pagestruct id @date(t): the page becomes a panel."""
        self.run(f"smpl full\nsetobs {unit} {time} --panel-vars", check=True)
        self._read_range()
        self.refresh()

    def copy_between(self, src_page: str, src: str, dst_page: str, dst: str, method: str = ""):
        """EViews copy(c=...) page\\series [page\\]name: frequency conversion between pages."""
        for pg in (src_page, dst_page):
            if pg not in self.wf.pages:
                raise GretlError(f"no page called {pg}")
        cur = self.wf.page
        marg = f', "{method}"' if method else ""
        self._save_page()
        self.run(f'clear --dataset\nopen "{self._page_file(src_page)}" --quiet --preserve\n'
                 f"matrix ev_cv = ev_pagecol({src})", check=True)
        self.run(f'clear --dataset\nopen "{self._page_file(dst_page)}" --quiet --preserve\n'
                 f"series {dst} = ev_freqconv(ev_cv{marg})", check=True)
        if dst_page != cur:
            self.run(f'smpl full\nstore "{self._page_file(dst_page)}"\n'
                     f'clear --dataset\nopen "{self._page_file(cur)}" --quiet --preserve', check=True)
        self._enter_page(cur)

    def stack_page(self, name: str, patterns: list[str]):
        """EViews pagestack: pool series x_? (one per unit) become one series of a new panel page."""
        if name in self.wf.pages:
            raise GretlError(f"page {name} already exists")
        cmds = ["smpl full", f'strings ev_sid = ev_stackids("{patterns[0]}", dataset)']
        cmds += [f'matrix ev_stk{k} = ev_stack("{p}", dataset, ev_sid)' for k, p in enumerate(patterns, 1)]
        cmds += ["scalar ev_T = rows(ev_stk1)", "scalar ev_NS = nelem(ev_sid)", "matrix ev_idv = seq(1, ev_NS)'",
                 "loop ev_j = 1..ev_NS", "scalar ev_v = atof(ev_sid[ev_j])", "if ok(ev_v)",
                 "ev_idv[ev_j] = ev_v", "endif", "endloop"]
        self.run("\n".join(cmds), check=True)
        self._save_page()
        body = ["scalar ev_NT = ev_T * ev_NS", "nulldata ev_NT --preserve",
                "series crossid = vec(ones(ev_T, 1) * ev_idv')",
                "series period = vec(seq(1, ev_T)' * ones(1, ev_NS))"]
        body += [f"series {p.replace('?', '')} = vec(ev_stk{k})" for k, p in enumerate(patterns, 1)]
        body += ["setobs crossid period --panel-vars"]
        self.run("\n".join(body), check=True)
        self.wf.pages.append(name)
        self.wf.page_lists[name] = {}
        self._enter_page(name)

    def unstack_page(self, name: str, unit: str, time: str, series: list[str], pattern: str = "*?"):
        """EViews pageunstack: a new page with one series per cross-section unit."""
        if name in self.wf.pages:
            raise GretlError(f"page {name} already exists")
        if not self.is_panel():
            raise GretlError("the current page is not a panel (Proc > Structure first)")
        cmds = ["smpl full", f"matrix ev_uid = ev_panelids({unit})",
                f"matrix ev_ut = ev_unstack({time})[,1]"]
        cmds += [f"matrix ev_u{k} = ev_unstack({x})" for k, x in enumerate(series, 1)]
        self.run("\n".join(cmds), check=True)
        self._save_page()
        body = ["scalar ev_T = rows(ev_ut)", "nulldata ev_T --preserve", f"series {time} = ev_ut"]
        for k, x in enumerate(series, 1):
            nm = pattern.replace("*", x).replace("?", "%g")
            body += [f"loop ev_j = 1..cols(ev_u{k})", f'string ev_nm = sprintf("{nm}", ev_uid[ev_j])',
                     f"series @ev_nm = ev_u{k}[,ev_j]", "endloop"]
        self.run("\n".join(body), check=True)
        self.wf.pages.append(name)
        self.wf.page_lists[name] = {}
        self._enter_page(name)
