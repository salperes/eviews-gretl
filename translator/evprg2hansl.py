#!/usr/bin/env python3
"""Translate EViews programs (.prg) into gretl hansl scripts (.inp).

The output relies on the EViewsCompat gretl package for estimation
(ev_ls, ev_wald, ev_diag, ev_freeze, ev_fit, ev_resid) and the @-functions.

Usage:
    python3 evprg2hansl.py program.prg [-o program.inp] [--case keep|upper|lower]

Lines the translator cannot handle are kept as "# TODO(EViews ...)" comments,
and lines with no gretl meaning (cd, close, graph styling) as
"# ignored(EViews): ..."; both are listed in a summary on stderr.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from dataclasses import dataclass, field


class Ignored(Exception):
    """Statement has no effect in gretl (cd, close, graph styling...)."""


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

# hansl words that cannot be used as variable names
HANSL_RESERVED = {
    "list", "series", "scalar", "matrix", "string", "strings", "bundle", "bundles",
    "matrices", "lists", "array", "end", "data", "lags", "const", "loop", "if",
    "else", "elif", "endif", "endloop", "function", "return", "print", "open",
    "smpl", "delete", "set", "quit", "include", "run", "genr", "join", "store",
    "var", "vecm", "ols", "tsls", "garch", "arima", "eval", "catch", "null",
    "obs", "time", "index", "dummy", "void", "type", "range", "values",
}


@dataclass
class Ctx:
    case: str = "keep"
    scalars: set = field(default_factory=set)
    strings: set = field(default_factory=set)
    index_vars: set = field(default_factory=set)     # for !i = ...
    foreach_vars: set = field(default_factory=set)   # for %x ...
    groups: dict = field(default_factory=dict)       # name -> members
    equations: dict = field(default_factory=dict)    # name -> "ls" | "arch"
    graphs: set = field(default_factory=set)
    last_eq: str | None = None
    todos: list = field(default_factory=list)
    ignored: list = field(default_factory=list)
    eq_counter: int = 0
    need_N: bool = False
    plot_files: bool = False
    plot_counter: int = 0
    default_db: str | None = None
    page: str = "page1"
    pages: set = field(default_factory=lambda: {"page1"})
    group_page: dict = field(default_factory=dict)    # group -> page it lives on
    need_pages: bool = False
    var_counter: int = 0
    systems: dict = field(default_factory=dict)     # name -> {"eqs": [...], "inst": "..."}
    eq_dep: dict = field(default_factory=dict)      # equation -> dependent expression
    matrices: dict = field(default_factory=dict)    # matrix -> (rows, cols)
    models: dict = field(default_factory=dict)      # model -> {"eqs": [...], "ids": [...]}
    var_endo: dict = field(default_factory=dict)    # VAR name -> series names of its variables


def safe_name(name: str, prefix: str) -> str:
    return prefix + name if name.lower() in HANSL_RESERVED else name


def apply_case(name: str, ctx: Ctx) -> str:
    if ctx.case == "upper":
        return name.upper()
    if ctx.case == "lower":
        return name.lower()
    return name


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

# EViews function -> hansl/EViewsCompat function (case-insensitive, followed by "(")
FUNC_MAP = [
    ("dlog", "ldiff"), ("d", "diff"), ("log", "log"), ("exp", "exp"),
    ("abs", "abs"), ("sqr", "sqrt"),
    ("@pchy", "ev_pchy"), ("@pcy", "ev_pcy"), ("@pch", "ev_pch"), ("@pc", "ev_pc"),
    ("@movav", "ev_movav"), ("@movsum", "ev_movsum"), ("@cumsum", "cum"),
    ("@mean", "ev_mean"), ("@stdev", "ev_stdev"), ("@var", "ev_var"),
    ("@obs", "ev_obs"), ("@elem", "ev_elem"), ("@seas", "ev_seas"),
    ("@abs", "abs"), ("@log", "log"), ("@exp", "exp"), ("@sqrt", "sqrt"),
    ("@round", "round"), ("@floor", "floor"), ("@ceiling", "ceil"),
    ("@sum", "sum"), ("@min", "min"), ("@max", "max"), ("@median", "median"),
    ("@qnorm", "invcdf(z, "), ("@cnorm", "cnorm"), ("@dnorm", "dnorm"),
]

# words without arguments
KEYWORD_MAP = [
    (r"@trend(\(\))?", "ev_trend()"),
    (r"@obsnum", "obs"),
    (r"@obssmpl", "$nobs"),
    (r"@obsrange", "ev_N"),
    (r"@year", "$obsmajor"),
    (r"@quarter", "$obsminor"),
    (r"@month", "$obsminor"),
    (r"@first", "1"),
    (r"@last", "ev_N"),
    (r"nrnd(?!\s*\()", "normal()"),
    (r"rnd(?!\s*\()", "uniform()"),
    (r"na\b", "NA"),
]


def _func_re(name: str) -> re.Pattern:
    lead = "" if name.startswith("@") else r"(?<![A-Za-z0-9_.@$])"
    return re.compile(lead + re.escape(name) + r"\s*\(", re.IGNORECASE)


_FUNC_RES = [(_func_re(src), dst if dst.endswith(" ") else dst + "(") for src, dst in FUNC_MAP]
_KEY_RES = [(re.compile(r"(?<![A-Za-z0-9_$])" + src + r"(?![A-Za-z0-9_])", re.IGNORECASE), dst)
            for src, dst in KEYWORD_MAP]


def _split_strings(s: str):
    """Yield (is_string_literal, chunk) pieces so literals stay untouched."""
    for i, part in enumerate(re.split(r'("[^"]*")', s)):
        yield i % 2 == 1, part


def program_vars(p: str, ctx: Ctx) -> str:
    """EViews program variables -> hansl.

    {!i} and !i glued to a name (x_!i) are textual: -> $i (index loops).
    {%x} is textual: -> $x for a foreach variable, @x for a string variable.
    A free-standing !i / %x is a value: -> i / x.
    """
    def braced_str(m):
        v = m.group(1)
        return f"${v}" if v in ctx.foreach_vars else f"@{safe_name(v, 's_')}"
    p = re.sub(r"\{!(\w+)\}", lambda m: f"${safe_name(m.group(1), 'v_')}", p)
    p = re.sub(r"\{%(\w+)\}", braced_str, p)
    p = re.sub(r"(?<=[A-Za-z0-9_])!(\w+)", lambda m: f"${safe_name(m.group(1), 'v_')}", p)
    p = re.sub(r"!(\w+)", lambda m: safe_name(m.group(1), "v_"), p)
    p = re.sub(r"%(\w+)", lambda m: m.group(1) if m.group(1) in ctx.foreach_vars
               else safe_name(m.group(1), "s_"), p)
    return p


def translate_expr(expr: str, ctx: Ctx, condition: bool = False) -> str:
    expr = expr.strip()
    out = []
    for is_lit, part in _split_strings(expr):
        if is_lit:
            out.append(part)
            continue
        p = program_vars(part, ctx)
        if re.search(r"@first|@last|@obsrange", p, re.IGNORECASE):
            ctx.need_N = True
        for rx, dst in _FUNC_RES:
            p = rx.sub(dst, p)
        for rx, dst in _KEY_RES:
            p = rx.sub(dst, p)
        # @coefs(k) and resid refer to the last estimated equation
        if re.search(r"@coefs\s*\(", p, re.IGNORECASE) or re.search(r"(?<![A-Za-z0-9_])resid(?![A-Za-z0-9_])", p, re.IGNORECASE):
            if not ctx.last_eq:
                raise ValueError("@coefs/resid used before any equation")
            eq = ctx.last_eq
            p = re.sub(r"@coefs\s*\(\s*([^()]+?)\s*\)", rf"{eq}.coeff[\1]", p, flags=re.IGNORECASE)
            res = f"ev_resid({eq})" if ctx.equations.get(eq) == "ls" else f"{eq}_resid"
            p = re.sub(r"(?<![A-Za-z0-9_])resid(?![A-Za-z0-9_])", res, p, flags=re.IGNORECASE)
        # group element g(i) -> g[i]
        for g in ctx.groups:
            p = re.sub(rf"(?<![A-Za-z0-9_.$]){re.escape(g)}\s*\(\s*([^()-][^()]*)\)", rf"{g}[\1]", p)
        p = p.replace("<>", "!=")
        p = re.sub(r"\band\b", "&&", p, flags=re.IGNORECASE)
        p = re.sub(r"\bor\b", "||", p, flags=re.IGNORECASE)
        p = re.sub(r"\bnot\b", "!", p, flags=re.IGNORECASE)
        if condition:
            p = re.sub(r"(?<![<>!=])=(?!=)", "==", p)
        if ctx.case != "keep":
            p = case_names(p, ctx)
        out.append(p)
    return "".join(out)


_KEEP_CASE = {"NA", "obs", "const", "ev_N", "z"}
# names that are functions (not series lags) when followed by "("
_FUNC_NAMES = {src.lstrip("@").lower() for src, _ in FUNC_MAP} | {
    "ldiff", "diff", "log", "exp", "abs", "sqrt", "invcdf", "cnorm", "dnorm", "cum", "round",
    "floor", "ceil", "sum", "min", "max", "median", "mean", "sd", "uniform", "normal",
    "hpfilt", "movavg", "lag", "ok", "missing", "nobs"}


def case_names(p: str, ctx: Ctx) -> str:
    """Apply --case to series names, including lagged ones like x(-1), but not to functions."""
    def fix(m):
        name, paren = m.group(1), m.group(2)
        if paren and (name.lower() in _FUNC_NAMES or name.startswith("ev_")):
            return m.group(0)
        return _case_ident(name, ctx) + paren
    return re.sub(r"(?<![A-Za-z0-9_$@.])([A-Za-z][A-Za-z0-9_]*)(?![A-Za-z0-9_])(\s*\(?)", fix, p)


def _case_ident(name: str, ctx: Ctx) -> str:
    if name in _KEEP_CASE or name in ctx.index_vars or name in ctx.foreach_vars \
            or name in ctx.scalars or name in ctx.strings or name.startswith("ev_") \
            or name in ctx.groups or name in ctx.equations:
        return name
    return apply_case(name, ctx)


def translate_name(name: str, ctx: Ctx) -> str:
    """Left-hand-side object name (may hold program variables)."""
    return apply_case(program_vars(name.strip(), ctx), ctx)


# ---------------------------------------------------------------------------
# Dates and samples
# ---------------------------------------------------------------------------

def translate_date(tok: str) -> str | None:
    """Return a gretl observation label for a plain EViews date, else None."""
    t = tok.strip()
    m = re.fullmatch(r"(\d{4})[qQ:](\d)", t)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    m = re.fullmatch(r"(\d{4})[mM](\d{1,2})", t)
    if m:
        return f"{m.group(1)}:{int(m.group(2)):02d}"
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m:
        mo, d, y = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    if re.fullmatch(r"\d{4}", t):
        return t
    return None


def _smpl_point(tok: str, var: str, out: list, ctx: Ctx) -> str:
    plain = translate_date(tok)
    if plain:
        return plain
    # {!y}q1 or !y with a period
    m = re.fullmatch(r"\{?!(\w+)\}?(?:([qQmM])(\d{1,2}))?", tok)
    if m and m.group(2):
        v, f, p = m.groups()
        fmt = f"%d:{int(p)}" if f.lower() == "q" else f"%d:{int(p):02d}"
        out.append(f'scalar {var} = obsnum(sprintf("{fmt}", {safe_name(v, "v_")}))')
        return var
    # observation arithmetic: @first+!i, @last-4, !n ...
    expr = translate_expr(tok, ctx)
    if re.fullmatch(r"\d+|[A-Za-z_]\w*", expr):
        return expr
    out.append(f"scalar {var} = {expr}")
    return var


def translate_smpl(args: str, ctx: Ctx) -> list[str]:
    cond = None
    m = re.search(r"\bif\b", args, flags=re.IGNORECASE)
    if m:
        cond = args[m.end():].strip()
        args = args[:m.start()]
    toks = args.split()
    # EViews smpl always starts from the whole workfile
    out = ["smpl full"]
    if toks and [t.lower() for t in toks] != ["@all"]:
        if len(toks) != 2:
            raise ValueError("smpl needs a start and an end (or a sample object)")
        a, b = toks
        start = _smpl_point(a, "ev_t1", out, ctx)
        end = _smpl_point(b, "ev_t2", out, ctx)
        out.append(f"smpl {start} {end}")
    if cond:
        out.append(f"smpl {translate_expr(cond, ctx, condition=True)} --restrict")
    return out


def _parse_dmy(s: str) -> dt.date:
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if not m:
        raise ValueError(f"bad daily date {s}")
    mo, d, y = map(int, m.groups())
    return dt.date(y, mo, d)


def workfile(freq: str, start: str, end: str) -> list[str]:
    f = freq.lower()
    if f in ("a", "y"):
        return [f"nulldata {int(end) - int(start) + 1}", f"setobs 1 {start} --time-series"]
    if f in ("q", "m"):
        per = 4 if f == "q" else 12
        def parse(s, default):
            m = re.fullmatch(r"(\d{4})(?:[qQmM:](\d{1,2}))?", s)
            if not m:
                raise ValueError(f"bad date {s}")
            return int(m.group(1)), int(m.group(2) or default)
        y0, p0 = parse(start, 1)
        y1, p1 = parse(end, per)
        n = (y1 - y0) * per + (p1 - p0) + 1
        label = f"{y0}:{p0}" if f == "q" else f"{y0}:{p0:02d}"
        return [f"nulldata {n}", f"setobs {per} {label} --time-series"]
    if f in ("d5", "d", "d7"):
        d0, d1 = _parse_dmy(start), _parse_dmy(end)
        days = [d0 + dt.timedelta(k) for k in range((d1 - d0).days + 1)]
        per = 7 if f == "d7" else 5
        if per == 5:
            days = [d for d in days if d.weekday() < 5]
        return [f"nulldata {len(days)}", f"setobs {per} {days[0].isoformat()} --time-series"]
    raise ValueError(f"unsupported workfile frequency {freq}")


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------

LS_OPT_COV = {"white": "white", "h": "white", "hac": "hac", "n": "hac"}


def _ls_cov(opts: str | None) -> str | None:
    if not opts:
        return None
    for o in (x.strip().lower() for x in opts.split(",")):
        if o.startswith("cov="):
            o = o[4:]
        if o in LS_OPT_COV:
            return LS_OPT_COV[o]
    return None


def _spec(spec: str, ctx: Ctx) -> str:
    spec = program_vars(spec.strip(), ctx)
    if ctx.case != "keep":
        spec = " ".join(t if t.lower() == "c" else case_names(t, ctx) for t in spec.split())
    return spec


def _ls_call(name: str, opts: str | None, spec: str, ctx: Ctx) -> list[str]:
    name = translate_name(name, ctx)
    ctx.equations[name] = "ls"
    ctx.last_eq = name
    sp = _spec(spec, ctx)
    ctx.eq_dep[name] = sp.split("=", 1)[0].strip() if "=" in sp else sp.split()[0]
    cov = _ls_cov(opts)
    args = f'"{_spec(spec, ctx)}", dataset' + (f', "{cov}"' if cov else "")
    return [f"bundle {name} = ev_ls({args})"]


def _arch_call(name: str, opts: str | None, spec: str, ctx: Ctx) -> list[str]:
    o = [x.strip().lower() for x in (opts or "1,1").split(",")]
    if any(x in ("t", "e", "tarch", "egarch") or x.startswith(("thrsh", "egarch", "archm")) for x in o):
        raise ValueError("TGARCH/EGARCH/ARCH-M need the gig package")
    nums = [x for x in o if re.fullmatch(r"\d+", x)]
    p, q = (nums + ["1", "1"])[:2]
    name = translate_name(name, ctx)
    ctx.equations[name] = "arch"
    ctx.last_eq = name
    toks = _spec(spec, ctx).split()
    dep, regs = toks[0], ["const" if t.lower() == "c" else translate_expr(t, ctx) for t in toks[1:]]
    # EViews arch(p,q): p = GARCH order, q = ARCH order; gretl garch p q likewise
    # EViews warns and continues when GARCH does not converge; so do we
    return [f"catch garch {p} {q} ; {translate_expr(dep, ctx)} {' '.join(regs)} --quiet",
            "if $error",
            f'printf "Warning: {name} (GARCH) did not converge; previous estimates kept\\n"',
            "else",
            f"bundle {name} = _(coeff = $coeff, vcv = $vcv, lnl = $lnl)",
            f"series {name}_h = $h",
            f"series {name}_resid = $uhat",
            "endif"]


def _plot_out(ctx: Ctx) -> str:
    if not ctx.plot_files:
        return "--output=display"
    ctx.plot_counter += 1
    return f'--output="plot{ctx.plot_counter:02d}.png"'


def _graph_cmd(kind: str, members: list[str], ctx: Ctx) -> list[str]:
    if kind == "scat":
        if len(members) == 1 and members[0] in ctx.groups:
            members = ctx.groups[members[0]]
        if len(members) < 2:
            raise ValueError("scatter needs two series")
        members = members[1:] + members[:1]   # gretl: x variable last
        return [f"gnuplot {' '.join(members)} {_plot_out(ctx)}"]
    style = "--with-boxes" if kind == "bar" else "--with-lines"
    return [f"gnuplot {' '.join(members)} --time-series {style} {_plot_out(ctx)}"]


GRAPH_KINDS = {"line", "bar", "scat", "scatter", "area", "spike"}
GRAPH_STYLING = {"addtext", "setelem", "axis", "legend", "options", "save", "draw",
                 "name", "datelabel", "scale", "align", "template", "setfont",
                 "addarrow", "setobslabel", "displayname", "label"}


def _uroot(series: str, opts: str | None, ctx: Ctx) -> list[str]:
    o = {}
    for x in (opts or "adf").split(","):
        k, _, v = x.strip().lower().partition("=")
        o[k] = v
    test = "adf" if "adf" in o or not ({"kpss", "pp", "llc", "ips", "df", "ers", "np"} & o.keys()) else None
    det = "--ct" if "trend" in o else ("--nc" if "none" in o else "--c")
    diff = " --difference" if o.get("dif", "0") not in ("", "0") else ""
    lag = o.get("maxlag") or o.get("lag") or "4"
    x = translate_name(series, ctx)
    if test == "adf":
        info = o.get("info", "")
        down = {"aic": " --test-down=AIC", "sic": " --test-down=BIC", "bic": " --test-down=BIC",
                "hqc": " --test-down=tstat", "tstat": " --test-down=tstat"}.get(info, "")
        return [f"adf {lag} {x} {det}{diff}{down}"]
    if "kpss" in o:
        return [f"kpss {o.get('lag', '-1')} {x}" + (" --trend" if "trend" in o else "")]
    if "llc" in o:
        return [f"levinlin {lag} {x}" + (" --ct" if "trend" in o else "")]
    raise ValueError(f"unit root test {'/'.join(o)} has no gretl equivalent here")


def _strip_comment(line: str) -> str:
    out, in_str = [], False
    for ch in line:
        if ch == '"':
            in_str = not in_str
        if ch == "'" and not in_str:
            break
        out.append(ch)
    return "".join(out).rstrip()


def _opts(text: str | None) -> dict:
    """EViews option list "d=mydb, page=q, e" -> {"d": "mydb", "page": "q", "e": ""}."""
    out = {}
    for x in (text or "").split(","):
        k, _, v = x.strip().partition("=")
        if k:
            out[k.strip().lower()] = v.strip().strip('"')
    return out


def _plot_file_arg(ctx: Ctx) -> str:
    if not ctx.plot_files:
        return ""
    ctx.plot_counter += 1
    return f', "plot{ctx.plot_counter:02d}.png"'


def _forecast_call(o: str, opts: str | None, args: str, ctx: Ctx, dynamic: bool) -> list[str]:
    names = args.split()
    if not names:
        raise ValueError("forecast needs a name for the forecast series")
    op = _opts(opts)
    if "s" in op:
        dynamic = False
    # EViews forecasts the underlying series (Y for dlog(Y)) unless option d asks
    # for the dependent expression itself
    level = 0 if "d" in op else 1
    quiet = 0 if "e" in op else 1
    res = [f"bundle {o}_fc = ev_forecast({o}, dataset, {int(dynamic)}, {quiet}, {level})",
           f"series {translate_name(names[0], ctx)} = ev_fcast_series({o}_fc, {o}_fc.level)"]
    if len(names) > 1:
        res.append(f"series {translate_name(names[1], ctx)} = ev_fcast_se({o}_fc, {o}_fc.level)")
    if "g" in op:
        res.append(f"ev_fplot(&{o}_fc{_plot_file_arg(ctx)})")
    return res


def _var_call(name: str, opts: str | None, spec: str, ctx: Ctx) -> list[str]:
    """var v.ls 1 2 y1 y2 @ c x: expressions become top-level series first,
    so that the VAR's lags can use pre-sample observations."""
    name = translate_name(name, ctx)
    ctx.equations[name] = "var"
    ctx.last_eq = name
    left, _, right = program_vars(spec, ctx).partition("@")
    toks = left.split()
    i = 0
    lagp = []
    while i + 1 < len(toks) and toks[i].isdigit() and toks[i + 1].isdigit():
        lagp += toks[i:i + 2]
        i += 2
    if not lagp:
        raise ValueError("VAR needs lag pairs, e.g. 1 2")
    endo, exo = toks[i:], right.split()
    pre, names, spec_t = [], [], []
    for t in endo + exo:
        if t.lower() == "c":
            continue
        names.append(t)
        if re.fullmatch(r"[A-Za-z_]\w*", t):
            spec_t.append(apply_case(t, ctx))
        else:
            ctx.var_counter += 1
            v = f"ev_v{ctx.var_counter}"
            pre.append(f"series {v} = {translate_expr(t, ctx)}")
            spec_t.append(v)
    if pre:
        # build them over the whole workfile so that lags can use pre-sample data
        pre = ["scalar ev_s1 = $t1", "scalar ev_s2 = $t2", "smpl full"] + pre + ["smpl ev_s1 ev_s2"]
    ne = len(endo)
    ctx.var_endo[name] = spec_t[:ne]
    out_spec = " ".join(lagp + spec_t[:ne])
    if right or "@" in spec:
        out_spec += " @ " + " ".join((["c"] if any(t.lower() == "c" for t in exo) else []) + spec_t[ne:])
    if "noconst" in _opts(opts) and "@" not in out_spec:
        out_spec += " @"
    return pre + [f'bundle {name} = ev_varest("{out_spec.strip()}", dataset, 0, "{" ".join(names)}")']


def _vec_call(name: str, opts: str | None, spec: str, ctx: Ctx) -> list[str]:
    """var v.ec(case, rank) lags y1 y2 [@ x]  ->  ev_vecm."""
    case, rank = "c", "1"
    for x in (opts or "").split(","):
        x = x.strip().lower()
        if x in ("a", "b", "c", "d", "e"):
            case = x
        elif x.isdigit():
            rank = x
    out = _var_call(name, None, spec, ctx)          # builds helper series, records the object
    ctx.equations[translate_name(name, ctx)] = "vecm"
    last = out[-1]
    m = re.fullmatch(r'bundle (\S+) = ev_varest\("([^"]*)", dataset, 0, "([^"]*)"\)', last)
    out[-1] = f'bundle {m.group(1)} = ev_vecm("{m.group(2)}", dataset, "{case}", {rank}, 0, "{m.group(3)}")'
    return out


def _split_terms(rhs: str) -> list[str]:
    """Split a right-hand side at top-level + and - (keeping the sign)."""
    terms, depth, cur = [], 0, ""
    for i, ch in enumerate(rhs):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch in "+-" and depth == 0 and cur.strip() and not cur.rstrip().endswith(("*", "/", "^", "e", "E")):
            terms.append(cur)
            cur = ch
            continue
        cur += ch
    if cur.strip():
        terms.append(cur)
    return [t.strip() for t in terms]


def _linear_equation(line: str) -> tuple[str, str, str]:
    """'y = c(1) + c(2)*x - c(3)*z' -> ('y', 'c x (-(z))', '1 2 3')."""
    if "=" not in line:
        raise ValueError("system equations must be written as y = c(1) + c(2)*x ...")
    lhs, rhs = line.split("=", 1)
    xs, cs = [], []
    for t in _split_terms(rhs.replace(" ", "")):
        sign = -1 if t.startswith("-") else 1
        t = t.lstrip("+-")
        m = re.fullmatch(r"(?i)c\((\d+)\)", t)
        if m:
            if sign < 0:
                raise ValueError("a negative intercept term is not supported")
            xs.append("c")
            cs.append(m.group(1))
            continue
        m = re.fullmatch(r"(?i)c\((\d+)\)\*(.+)", t) or re.fullmatch(r"(?i)(.+)\*c\((\d+)\)", t)
        if not m:
            raise ValueError("system equations must be linear in c(i)")
        num, expr = (m.group(1), m.group(2)) if t.lower().startswith("c(") else (m.group(2), m.group(1))
        if re.search(r"(?i)(?<![A-Za-z0-9_])c\(\d+\)", expr):
            raise ValueError("system equations must be linear in c(i)")
        xs.append(expr if sign > 0 else f"(-({expr}))")
        cs.append(num)
    return lhs.strip().replace(" ", ""), " ".join(xs), " ".join(cs)


def _system_estimate(o: str, method: str, ctx: Ctx) -> list[str]:
    sysd = ctx.systems.get(o)
    if not sysd or not sysd["eqs"]:
        raise ValueError(f"system {o} has no equations")
    deps, xs, cs, txt = [], [], [], []
    for ln in sysd["eqs"]:
        d, x, c = _linear_equation(program_vars(ln, ctx))
        deps.append(case_names(d, ctx) if ctx.case != "keep" else d)
        xs.append(_spec(x, ctx))
        cs.append(c)
        txt.append(re.sub(r"\s+", "", ln).upper())
    q = lambda arr: ", ".join(f'"{a}"' for a in arr)
    inst = _spec(sysd["inst"], ctx) if sysd["inst"] else ""
    ctx.equations[o] = "system"
    ctx.last_eq = o
    return [f"strings ev_sd = defarray({q(deps)})",
            f"strings ev_sx = defarray({q(xs)})",
            f"strings ev_sc = defarray({q(cs)})",
            f"strings ev_st = defarray({q(txt)})",
            f'bundle {o} = ev_system(ev_sd, ev_sx, ev_sc, dataset, "{method}", "{inst}", 1, ev_st)',
            f'{o}.name = "{o.upper()}"',
            f"ev_sysprint(&{o})"]


def _fiml_estimate(o: str, ctx: Ctx) -> list[str]:
    """FIML: gretl's system command at the top level, then ev_sysfrom."""
    sysd = ctx.systems[o]
    pre, eqlines, deps, txt, kk = [], [], [], [], []
    pos_of, cu, pos = {}, [], 0
    restr = []
    helper = {}

    def series_for(expr):
        e = case_names(expr, ctx) if ctx.case != "keep" else expr
        if re.fullmatch(r"[A-Za-z_]\w*", e):
            return e
        if e not in helper:
            ctx.var_counter += 1
            helper[e] = f"ev_f{ctx.var_counter}"
            pre.append(f"series {helper[e]} = {translate_expr(e, ctx)}")
        return helper[e]
    for i, ln in enumerate(sysd["eqs"], 1):
        d, x, c = _linear_equation(program_vars(ln, ctx))
        dep = series_for(d)
        regs, nums = [], c.split()
        for j, (t, num) in enumerate(zip(x.split(), nums), 1):
            regs.append("const" if t == "c" else series_for(t))
            pos += 1
            if num in pos_of:
                pi, pj = pos_of[num][1:]
                restr.append(f"  b[{pi},{pj}] - b[{i},{j}] = 0")
            else:
                pos_of[num] = (pos, i, j)
                cu.append(num)
        eqlines.append(f"  equation {dep} {' '.join(regs)}")
        deps.append(d.upper())
        txt.append(re.sub(r"\s+", "", ln).upper())
        kk.append(str(len(regs)))
    endog = " ".join(series_for(_linear_equation(program_vars(ln, ctx))[0]) for ln in sysd["eqs"])
    sname = f"ev_fs_{o}"
    q = lambda arr: ", ".join(f'"{a}"' for a in arr)
    out = ["scalar ev_s1 = $t1", "scalar ev_s2 = $t2", "smpl full"] + pre + ["smpl ev_s1 ev_s2"] if pre else []
    out += [f"{sname} <- system"] + eqlines + [f"  endog {endog}", "end system"]
    if restr:
        out += [f"restrict {sname}"] + restr + ["end restrict"]
    out += [f"estimate {sname} method=fiml --quiet",
            f"strings ev_sd = defarray({q(deps)})",
            f"strings ev_st = defarray({q(txt)})",
            f'bundle {o} = ev_sysfrom("fiml", $coeff, $vcv, $uhat, $yhat, '
            f'{{{", ".join(str(pos_of[n][0]) for n in cu)}}}, {{{", ".join(cu)}}}, {{{", ".join(kk)}}}, '
            f"ev_sd, ev_st, $t1, $lnl, 1)",
            f'{o}.name = "{o.upper()}"',
            f"ev_sysprint(&{o})"]
    ctx.equations[o] = "system"
    return out


_DEP_RE = [(r"^\s*([A-Za-z_]\w*)\s*$", 0), (r"(?i)^\s*log\(\s*([A-Za-z_]\w*)\s*\)\s*$", 1),
           (r"(?i)^\s*d\(\s*([A-Za-z_]\w*)\s*\)\s*$", 2), (r"(?i)^\s*dlog\(\s*([A-Za-z_]\w*)\s*\)\s*$", 3),
           (r"(?i)^\s*d\(\s*log\(\s*([A-Za-z_]\w*)\s*\)\s*\)\s*$", 3)]


def _dep_base(dep: str) -> str:
    for rx, _ in _DEP_RE:
        m = re.match(rx, dep)
        if m:
            return m.group(1)
    raise ValueError(f"model: '{dep}' must be Y, log(Y), d(Y) or dlog(Y) of a series")


def _model_solve(o: str, opts: str | None, ctx: Ctx) -> list[str]:
    md = ctx.models[o]
    if not md["eqs"] and not md["ids"]:
        raise ValueError(f"model {o} is empty")
    dynamic = 0 if re.search(r"(?i)d\s*=\s*s", opts or "") else 1
    names = []
    for e in md["eqs"]:
        if e not in ctx.eq_dep:
            raise ValueError(f"model {o}: equation {e} is not known here")
        names.append(_dep_base(ctx.eq_dep[e]))
    ids = []
    for ln in md["ids"]:
        lhs, rhs = ln.split("=", 1)
        lhs = case_names(lhs.strip(), ctx) if ctx.case != "keep" else lhs.strip()
        rhs = case_names(rhs.strip(), ctx) if ctx.case != "keep" else rhs.strip()
        names.append(_dep_base(lhs))
        ids.append(f"{lhs} = {rhs}")
    q = lambda arr: ", ".join(f'"{a}"' for a in arr)
    out = [f"bundles ev_mb = defarray({', '.join(md['eqs'])})" if md["eqs"] else "bundles ev_mb = array(0)",
           f"strings ev_mi = defarray({q(ids)})" if ids else "strings ev_mi = array(0)",
           f"bundle {o} = ev_modelsolve(ev_mb, ev_mi, dataset, {dynamic})"]
    out += [f"series {n}_0 = ev_modelseries({o}, {k})" for k, n in enumerate(names, 1)]
    return out


def _object_method(obj: str, meth: str, opts: str | None, args: str, ctx: Ctx) -> list[str]:
    ml = meth.lower()
    o = translate_name(obj, ctx)
    if o in ctx.systems or ctx.equations.get(o) == "system":
        sysd = ctx.systems.setdefault(o, {"eqs": [], "inst": ""})
        if ml == "append":
            a = args.strip()
            if re.match(r"(?i)inst\s", a):
                sysd["inst"] = (sysd["inst"] + " " + a[4:].strip()).strip()
            else:
                sysd["eqs"].append(a)
            return [f"# system {o}: {a}"]
        meth_map = {"ls": "ls", "wls": "wls", "sur": "sur", "tsls": "tsls", "wtsls": "wtsls",
                    "3sls": "3sls", "gmm": "gmm"}
        if ml in meth_map:
            return _system_estimate(o, meth_map[ml], ctx)
        if ml == "fiml":
            return _fiml_estimate(o, ctx)
        if ml in ("output", "results", "display", "spec"):
            return [f"ev_sysprint(&{o})"]
        if ml in ("makeresids", "makeresid"):
            return [f"series {translate_name(n, ctx)} = ev_sysresid({o}, {k})"
                    for k, n in enumerate(args.split(), 1)]
        if ml == "wald":
            return [f'bundle {o}_wald = ev_wald({o}, "{args.strip()}")']
        raise ValueError(f"system method .{meth} not supported (use ls, wls, sur, tsls, wtsls, 3sls, gmm or fiml)")
    if ml == "svar":
        if ctx.equations.get(o) not in ("var", "vecm"):
            raise ValueError("svar needs a VAR")
        op = _opts(opts)
        if "lr" in op or "bq" in op or op.get("rtype", "").startswith("lr"):
            return [f"ev_svar_lr(&{o})"]
        a, b = op.get("namea"), op.get("nameb")
        if not a or not b:
            raise ValueError("svar: give rtype=patsr, namea=A, nameb=B (pattern matrices) or lr")
        return [f"ev_svar(&{o}, {translate_name(a, ctx)}, {translate_name(b, ctx)})"]
    if o in ctx.matrices and ml == "fill":
        r, c = ctx.matrices[o]
        vals = [v.strip() for v in args.split(",") if v.strip()]
        vals = ["NA" if v.lower() in ("na", "nan") else translate_expr(v, ctx) for v in vals]
        if len(vals) != r * c:
            raise ValueError(f"fill: {o} needs {r * c} values")
        byrow = _opts(opts).get("b", "c").lower().startswith("r")
        lit = "{" + ", ".join(vals) + "}"
        return [f"matrix {o} = mshape({lit}, {c}, {r})'" if byrow else f"matrix {o} = mshape({lit}, {r}, {c})"]
    if o in ctx.models:
        md = ctx.models[o]
        if ml == "merge":
            md["eqs"] += [translate_name(e, ctx) for e in args.split()]
            return [f"# model {o}: merge {args.strip()}"]
        if ml == "append":
            a = re.sub(r"(?i)^@identity\s+", "", args.strip())
            if "=" not in a:
                raise ValueError("model append: give an identity y = ...")
            md["ids"].append(program_vars(a, ctx))
            return [f"# model {o}: identity {a}"]
        if ml == "solve":
            return _model_solve(o, opts, ctx)
        raise ValueError(f"model method .{meth} not supported (merge, append, solve)")
    if ml == "coint":
        case, lag = "c", "4"
        for x in (opts or "").replace(",", " ").split():
            if x.lower() in ("a", "b", "c", "d", "e"):
                case = x.lower()
            elif x.isdigit():
                lag = x
        if o in ctx.groups:
            names = " ".join(ctx.groups[o])
        elif o in ctx.var_endo:
            names = " ".join(ctx.var_endo[o])
        else:
            raise ValueError("coint needs a group of series or a VAR")
        return [f'ev_coint("{names}", dataset, "{case}", {lag})']
    if ml == "ls":
        return _ls_call(obj, opts, args, ctx)
    if ml == "arch":
        return _arch_call(obj, opts, args, ctx)
    if ml == "wald":
        return [f'bundle {o}_wald = ev_wald({o}, "{args.strip()}")']
    if ml == "auto":
        return [f"bundle {o}_diag = ev_diag({o}, {(opts or '2').strip()})"]
    if ml in ("white", "hettest", "jbera"):
        return [f"bundle {o}_diag = ev_diag({o})"]
    if ml in ("output", "results", "display", "spec"):
        kind = ctx.equations.get(o)
        return [{"vecm": f"ev_vecprint(&{o})", "var": f"ev_varprint(&{o})"}.get(kind, f"ev_print(&{o})")]
    if ml == "resids":
        return [f"ev_plot(&{o})"]
    if ml in ("fit", "forecast") and ctx.equations.get(o, "ls") == "ls":
        # EViews: forecast = dynamic, fit = static, both over the current sample
        return _forecast_call(o, opts, args, ctx, dynamic=(ml == "forecast"))
    if ctx.equations.get(o) in ("var", "vecm"):
        h = (re.match(r"\s*(\d+)", opts or "") or re.match(r"\s*(\d+)", args or ""))
        h = h.group(1) if h else "10"
        if ml in ("output", "results", "display", "spec"):
            return [f"ev_vecprint(&{o})" if ctx.equations.get(o) == "vecm" else f"ev_varprint(&{o})"]
        if ml == "testexog" and ctx.equations.get(o) == "vecm":
            raise ValueError("Granger tests are for VAR objects")
        if ml == "impulse":
            if "t" in _opts(opts):
                return [f"matrix {o}_irf = ev_varirf({o}, {h})"]
            return [f"ev_varirfplot({o}, {h}{_plot_file_arg(ctx)})"]
        if ml == "decomp":
            return [f"matrix {o}_decomp = ev_vardecomp({o}, {h})"]
        if ml == "testexog":
            return [f"matrix {o}_granger = ev_vargranger({o})"]
        if ml == "laglen":
            m = re.match(r"\s*(\d+)", opts or args or "")
            return [f"ev_varlaglen({o}, dataset, {m.group(1) if m else 8})"]
        if ml in ("makeresids", "makeresid"):
            return [f"series {translate_name(n, ctx)} = ev_varresid({o}, {k})"
                    for k, n in enumerate(args.split(), 1)]
        if ml == "ls":
            return _var_call(obj, opts, args, ctx)
        raise ValueError(f"VAR view .{meth} not supported")
    if ml in ("makeresid", "makeresids") and ctx.equations.get(o) == "ls":
        return [f"series {translate_name(args.split()[0], ctx)} = ev_resid({o})"]
    if ml in ("makeresid", "makeresids") and ctx.equations.get(o) == "arch":
        return [f"series {translate_name(args.split()[0], ctx)} = {o}_resid"]
    if ml == "makegarch" and ctx.equations.get(o) == "arch":
        return [f"series {translate_name(args.split()[0], ctx)} = {o}_h"]
    if ml == "hpf":
        lam = re.search(r"lambda\s*=\s*([\d.]+)", opts or "")
        lam_arg = f", {lam.group(1)}" if lam else ""
        names = args.replace("@", " ").split()
        if not names:
            raise ValueError("hpf needs an output series")
        x = translate_name(obj, ctx)
        res = [f"series {translate_name(names[0], ctx)} = {x} - hpfilt({x}{lam_arg})"]
        if len(names) > 1:
            res.append(f"series {translate_name(names[1], ctx)} = hpfilt({x}{lam_arg})")
        return res
    if ml == "uroot":
        return _uroot(obj, opts, ctx)
    if ml == "stats":
        return [f"summary {o}"]
    if ml == "cor":
        return [f"corr {o}"]
    if ml in GRAPH_KINDS:
        if o in ctx.groups or not args:
            return _graph_cmd("scat" if ml.startswith("scat") else ml, [o], ctx)
    if ml in GRAPH_STYLING or o in ctx.graphs:
        raise Ignored("graph styling")
    raise ValueError(f"method .{meth} not supported")


def translate_line(line: str, ctx: Ctx) -> list[str]:
    s = line.strip()
    if not s:
        return [""]
    mo = re.match(r"([A-Za-z_]\w*)\(([^)]*)\)", s)     # command(options) may contain spaces
    if mo:
        first = mo.group(0)
        cmd_opts = mo.group(2)
    else:
        first = s.split()[0]
        cmd_opts = ""
    word = re.sub(r"\(.*", "", first.lower())          # command without (options)
    rest = s[len(first):].strip()

    # --- session / files
    if word in ("cd", "close", "output", "logmode", "mode", "wfclose"):
        raise Ignored(word)

    # --- databases: EViews .edb -> gretl .bin
    if word in ("dbopen", "db", "dbcreate"):
        name = re.sub(r"\.edb$", "", rest.split()[0].strip('"'), flags=re.IGNORECASE)
        ctx.default_db = name
        raise Ignored(f"default database is now {name}.bin")
    if word in ("store", "fetch"):
        op = _opts(cmd_opts)
        db = re.sub(r"\.edb$", "", op.get("d", "") or (ctx.default_db or ""), flags=re.IGNORECASE)
        names = [translate_name(n, ctx) for n in rest.split()]
        if not names:
            raise ValueError(f"{word} needs series names")
        if not db:
            raise ValueError(f"{word} needs a database: use {word}(d=name) or dbopen name")
        if word == "store":
            return [f'store "{db}.bin" {" ".join(names)} --database --overwrite']
        return [f'open "{db}.bin" --quiet', f'data {" ".join(names)} --quiet']

    # --- workfile pages (each page is kept as a .gdtb file in gretl's dot directory)
    if word in ("pagecreate", "pageselect", "pagedelete", "pagerename"):
        ctx.need_pages = True
        # the folder name is set again each time: opening data clears string variables
        save_cur = ["string ev_pagedir = $dotdir", "smpl full", f'store "@ev_pagedir/{ctx.page}.gdtb"']
        if word == "pagecreate":
            op = _opts(cmd_opts)
            new = op.get("page") or f"untitled{len(ctx.pages) + 1}"
            toks = rest.split()
            if toks and toks[0].lower() == "u":
                body = [f"nulldata {toks[1]} --preserve"]
            elif len(toks) >= 3:
                body = [ln + (" --preserve" if ln.startswith("nulldata") else "") for ln in workfile(*toks[:3])]
            else:
                raise ValueError("pagecreate needs frequency, start and end")
            ctx.pages.add(new)
            ctx.page = new
            return save_cur + body + ["scalar ev_N = $nobs"]
        if word == "pageselect":
            new = rest.split()[0]
            if new not in ctx.pages:
                raise ValueError(f"unknown page {new}")
            ctx.page = new
            relist = [f"list {g} = {' '.join(m)}" for g, m in ctx.groups.items()
                      if ctx.group_page.get(g) == new]
            return save_cur + [f'open "@ev_pagedir/{new}.gdtb" --quiet --preserve', "scalar ev_N = $nobs"] + relist
        if word == "pagedelete":
            name = rest.split()[0] if rest else ctx.page
            ctx.pages.discard(name)
            return ["string ev_pagedir = $dotdir", f'catch remove("@ev_pagedir/{name}.gdtb")']
        old, new = rest.split()[:2]
        ctx.pages.discard(old)
        ctx.pages.add(new)
        if ctx.page == old:
            ctx.page = new
            raise Ignored("renamed the current page")
        return ["string ev_pagedir = $dotdir", f'catch remove("@ev_pagedir/{new}.gdtb")',
                f'# page {old} renamed to {new}: next pageselect uses the new name']

    if word == "matrix":
        m = re.fullmatch(r"(?i)matrix\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*(\w+)", s)
        if m:
            r, c, name = int(m.group(1)), int(m.group(2)), translate_name(m.group(3), ctx)
            ctx.matrices[name] = (r, c)
            return [f"matrix {name} = zeros({r}, {c})"]
        raise ValueError("matrix: use matrix(rows, cols) name")
    if word == "model":
        name = translate_name(rest.split()[0], ctx) if rest else "model01"
        ctx.models[name] = {"eqs": [], "ids": []}
        ctx.equations[name] = "model"
        return [f"# model {name} declared"]
    if word == "system":
        name = translate_name(rest.split()[0], ctx) if rest else "sys01"
        ctx.systems[name] = {"eqs": [], "inst": ""}
        ctx.equations[name] = "system"
        return [f"# system {name} declared"]
    if word == "var":
        m = re.fullmatch(r"var\s+([\w{}!%$]+)\.ec(?:\(([^)]*)\))?\s+(.+)", s, flags=re.IGNORECASE)
        if m:
            return _vec_call(*m.groups(), ctx)
        m = re.fullmatch(r"var\s+([\w{}!%$]+)(?:\.ls(?:\(([^)]*)\))?\s+(.+))?", s, flags=re.IGNORECASE)
        if not m:
            raise ValueError("unsupported var statement")
        name, opts, spec = m.groups()
        if spec is None:
            ctx.equations[translate_name(name, ctx)] = "var"
            return [f"# VAR {name} declared (estimated later)"]
        return _var_call(name, opts, spec, ctx)
    if word in ("stop", "exit"):
        return ["quit"]
    if word in ("wfopen", "load", "import"):
        f = re.sub(r"\s.*$", "", rest.strip()) if not rest.startswith('"') else rest.split('"')[1]
        ctx.page = re.sub(r"\.\w+$", "", re.split(r"[\\/]", f)[-1]).lower() or "page1"
        ctx.pages = {ctx.page}
        return [f'open "{f}"', "scalar ev_N = $nobs"]
    if word == "read":
        f = rest.split('"')[1] if rest.startswith('"') else rest.split()[0]
        # EViews read adds series to the current workfile, like gretl append
        return [f'append "{f}"  # EViews read: check that the series names match']
    if word == "wfcreate":
        page = _opts(cmd_opts).get("page")
        if page:
            ctx.pages = {page}
            ctx.page = page
        toks = rest.split()
        if toks and toks[0].lower() == "u":
            return [f"nulldata {toks[1]}", "scalar ev_N = $nobs"]
        if len(toks) < 3:
            raise ValueError("wfcreate needs frequency, start and end")
        return workfile(toks[0], toks[1], toks[2]) + ["scalar ev_N = $nobs"]
    if word in ("wfsave", "save"):
        f = rest.split('"')[1] if rest.startswith('"') else rest.split()[0]
        f = re.split(r"[\\/]", f)[-1]
        f = re.sub(r"\.wf1$", "", f, flags=re.IGNORECASE)
        return [f'store "{f}.gdt"' if not f.endswith(".gdt") else f'store "{f}"']
    if word == "smpl":
        return translate_smpl(rest, ctx)
    if word == "sort":
        desc = "(d)" in first.lower()
        # gretl sorts only undated data: drop the time structure first
        return ["setobs 1 1 --cross-section  # sorting removes the date structure",
                f"dataset {'dsortby' if desc else 'sortby'} {translate_name(rest, ctx)}"]

    # --- control flow
    if word == "for":
        m = re.fullmatch(r"for\s+!(\w+)\s*=\s*(.+?)\s+to\s+(.+?)(?:\s+step\s+(.+))?",
                         s, flags=re.IGNORECASE)
        if m:
            v, a, b, step = m.groups()
            v = safe_name(v, "v_")
            ctx.index_vars.add(v)
            a, b = translate_expr(a, ctx), translate_expr(b, ctx)
            if step:
                st = translate_expr(step, ctx)
                cmp = ">=" if st.strip().startswith("-") else "<="
                return [f"loop for ({v}={a}; {v}{cmp}{b}; {v}+={st})"]
            return [f"loop {v} = {a}..{b}"]
        m = re.fullmatch(r"for\s+%(\w+)\s+(.+)", s, flags=re.IGNORECASE)
        if m:
            v, items = m.groups()
            ctx.foreach_vars.add(v)
            return [f"loop foreach {v} {program_vars(items, ctx)}"]
        raise ValueError("unsupported for loop")
    if word == "next":
        return ["endloop"]
    if word == "if":
        cond = re.sub(r"\s+then\s*$", "", rest, flags=re.IGNORECASE)
        return [f"if {translate_expr(cond, ctx, condition=True)}"]
    if word == "else":
        return ["else"]
    if word == "endif":
        return ["endif"]
    if word == "while":
        return [f"loop while {translate_expr(rest, ctx, condition=True)}"]
    if word == "wend":
        return ["endloop"]

    # --- declarations
    if word in ("series", "genr", "frml"):
        name, _, expr = rest.partition("=")
        name = translate_name(name, ctx)
        if not expr:
            return [f"series {name} = NA"]
        return [f"series {name} = {translate_expr(expr, ctx)}"]
    if word == "scalar":
        name, _, expr = rest.partition("=")
        name = safe_name(name.strip(), "v_")
        ctx.scalars.add(name)
        return [f"scalar {name} = {translate_expr(expr, ctx) if expr else 'NA'}"]
    if word == "group":
        toks = rest.split()
        name = translate_name(toks[0], ctx)
        members = [translate_name(t, ctx) for t in toks[1:]]
        ctx.groups[name] = members
        ctx.group_page[name] = ctx.page
        return [f"list {name} = {' '.join(members)}"]
    if word == "delete":
        return [f"catch delete {translate_name(n, ctx)}" for n in rest.split()]
    if word in ("show", "print"):
        res = []
        for n in rest.split():
            n = translate_name(n, ctx)
            if n in ctx.equations or n in ctx.graphs:
                continue        # already printed / drawn when created
            else:
                res.append(f"print {n}")
        if not res:
            raise Ignored("already printed or drawn when created")
        return res
    if word == "graph":
        m = re.fullmatch(r"graph\s+(\w+)\.(\w+)(?:\([^)]*\))?\s*(.*)", s, flags=re.IGNORECASE)
        if not m:
            raise ValueError("unsupported graph statement")
        gname, kind, args = m.groups()
        ctx.graphs.add(gname)
        kind = kind.lower()
        if kind not in GRAPH_KINDS:
            raise ValueError(f"graph type {kind} not supported")
        return _graph_cmd("scat" if kind.startswith("scat") else kind,
                          [translate_name(a, ctx) for a in args.split()], ctx)

    m = re.fullmatch(r"equation\s+([\w{}!%$]+)(?:\.(\w+)(?:\(([^)]*)\))?\s+(.+))?", s, flags=re.IGNORECASE)
    if m:
        name, meth, opts, spec = m.groups()
        if meth is None:
            return [f"# equation {name} declared (estimated later)"]
        if meth.lower() == "ls":
            return _ls_call(name, opts, spec, ctx)
        if meth.lower() == "arch":
            return _arch_call(name, opts, spec, ctx)
        raise ValueError(f"estimation method {meth} not supported")
    m = re.fullmatch(r"ls(?:\(([^)]*)\))?\s+(.+)", s, flags=re.IGNORECASE)
    if m:
        ctx.eq_counter += 1
        return _ls_call(f"eq_untitled{ctx.eq_counter}", m.group(1), m.group(2), ctx)

    # freeze(name) obj[.view(opts)]
    m = re.fullmatch(r"freeze\(([^)]*)\)\s+([\w{}!%$]+)(?:\.(\w+)(?:\(([^)]*)\))?)?\s*(.*)", s, flags=re.IGNORECASE)
    if m:
        tab, obj, view, opts, args = m.groups()
        tabn = translate_name(tab, ctx)
        o = translate_name(obj, ctx)
        if ctx.equations.get(o, "ls") == "ls" and (view is None or view.lower() == "output"):
            return [f'ev_freeze({o}, "{tabn}.txt")']
        if view is None:
            raise ValueError("freeze of this object not supported")
        if view.lower() in GRAPH_KINDS or view.lower() == "scat":
            ctx.graphs.add(tabn)
            return _object_method(obj, view, opts, args, ctx)
        inner = _object_method(obj, view, opts, args, ctx)
        ctx.graphs.add(tabn)        # frozen table: later .save etc. are ignored
        return [f'outfile "{tabn}.txt" --quiet'] + ["    " + x for x in inner] + ["end outfile"]

    # object methods: name.method(opts) args
    m = re.fullmatch(r"([\w{}!%$]+)\.(\w+)(?:\(([^)]*)\))?\s*(.*)", s)
    if m:
        return _object_method(*m.groups(), ctx)

    # assignments: !x = ..., %s = "...", g(!i) = ..., y = ...
    m = re.fullmatch(r"([!%]?)([\w{}!%$]+)\s*(?:\(([^()]+)\))?\s*=\s*(.+)", s)
    if m:
        sigil, name, elem, expr = m.groups()
        if elem is not None and translate_name(name, ctx) in ctx.matrices:
            v = "NA" if expr.strip().lower() == "na" else translate_expr(expr, ctx)
            return [f"{translate_name(name, ctx)}[{translate_expr(elem, ctx)}] = {v}"]
        if elem is not None:
            g = translate_name(name, ctx)
            if g not in ctx.groups:
                raise ValueError("element assignment to unknown object")
            idx = translate_expr(elem, ctx)
            return [f"strings ev_nms = varnames({g})",
                    f"string ev_nm = ev_nms[{idx}]",
                    f"series @ev_nm = {translate_expr(expr, ctx)}"]
        if sigil == "!":
            v = safe_name(name, "v_")
            ctx.scalars.add(v)
            return [f"scalar {v} = {translate_expr(expr, ctx)}"]
        if sigil == "%":
            v = safe_name(name, "s_")
            ctx.strings.add(v)
            return [f"string {v} = {translate_expr(expr, ctx)}"]
        if name in ctx.scalars:
            return [f"{name} = {translate_expr(expr, ctx)}"]
        return [f"series {translate_name(name, ctx)} = {translate_expr(expr, ctx)}"]

    raise ValueError("unsupported statement")


def translate(text: str, case: str = "keep") -> tuple[str, list[tuple[int, str]]]:
    hansl, todos, _ = translate_full(text, case)
    return hansl, todos


def translate_full(text: str, case: str = "keep", plot_files: bool = False):
    ctx = Ctx(case=case, plot_files=plot_files)
    raw = text.replace("\r\n", "\n").split("\n")
    lines, buf, start = [], "", 0
    for i, ln in enumerate(raw, 1):         # join continuation lines ending in " _"
        if not buf:
            start = i
        if re.search(r"\s_\s*$", _strip_comment(ln)):
            buf += re.sub(r"\s_\s*$", " ", _strip_comment(ln))
            continue
        lines.append((start, buf + ln))
        buf = ""

    body, indent, has_wf = [], 0, False
    for lineno, ln in lines:
        stripped = ln.strip()
        if stripped.startswith("'"):
            body.append("    " * indent + "#" + stripped.lstrip("'"))
            continue
        code = _strip_comment(ln)
        try:
            res = translate_line(code, ctx)
        except Ignored as e:
            ctx.ignored.append((lineno, stripped))
            body.append("    " * indent + f"# ignored(EViews line {lineno}, {e}): {code.strip()}")
            continue
        except ValueError as e:
            ctx.todos.append((lineno, stripped))
            body.append("    " * indent + f"# TODO(EViews line {lineno}, {e}): {code.strip()}")
            continue
        for r in res:
            if r.startswith("scalar ev_N"):
                has_wf = True
            head = r.split()[0] if r.strip() else ""
            if head in ("endloop", "endif", "else", "end"):
                indent = max(indent - 1, 0)
            body.append(("    " * indent + r) if r else "")
            if head in ("loop", "if", "else", "outfile"):
                indent += 1

    head = ["# Translated from EViews by evprg2hansl.py",
            "# Requires the EViewsCompat gretl package",
            "set verbose off",
            "include EViewsCompat.gfn"]
    if ctx.need_N and not has_wf:
        head.append("scalar ev_N = $nobs    # size of the workfile (EViews @last)")
    if ctx.need_pages:
        head.append("# workfile pages are kept as .gdtb files in gretl's dot directory (ev_pagedir)")
    return "\n".join(head + [""] + body) + "\n", ctx.todos, ctx.ignored


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("prg", help="EViews program file (.prg)")
    ap.add_argument("-o", "--output", help="output .inp (default: same name)")
    ap.add_argument("--case", choices=["keep", "upper", "lower"], default="keep",
                    help="change series-name case (hansl is case-sensitive)")
    ap.add_argument("--plot-files", action="store_true",
                    help="write graphs to plotNN.png instead of showing them (for gretlcli)")
    a = ap.parse_args(argv)
    with open(a.prg, encoding="utf-8", errors="replace") as f:
        text = f.read()
    hansl, todos, ignored = translate_full(text, a.case, a.plot_files)
    outp = a.output or re.sub(r"\.prg$", "", a.prg, flags=re.IGNORECASE) + ".inp"
    with open(outp, "w", encoding="utf-8") as f:
        f.write(hansl)
    print(f"Wrote {outp}", file=sys.stderr)
    if ignored:
        print(f"{len(ignored)} line(s) ignored (no gretl meaning, e.g. cd, graph styling)", file=sys.stderr)
    if todos:
        print(f"{len(todos)} line(s) need manual translation:", file=sys.stderr)
        for n, t in todos:
            print(f"  line {n}: {t}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
