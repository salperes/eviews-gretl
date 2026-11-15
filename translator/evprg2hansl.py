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
import itertools
import datetime as dt
import os
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
    matrix_values: dict = field(default_factory=dict)  # filled matrix -> grid of values
    texts: dict = field(default_factory=dict)       # text object -> lines
    models: dict = field(default_factory=dict)      # model -> {"eqs": [...], "ids": [...]}
    var_endo: dict = field(default_factory=dict)    # VAR name -> series names of its variables
    panel: tuple | None = None                      # (unit id, time) after pagestruct
    tables: set = field(default_factory=set)        # table objects (EViewsCompat bundles)
    page_panel: dict = field(default_factory=dict)  # page -> (unit id, time) of panel pages
    args_used: set = field(default_factory=set)     # program arguments %0 %1 ...


def safe_name(name: str, prefix: str) -> str:
    return prefix + name if name.lower() in HANSL_RESERVED else name


def apply_case(name: str, ctx: Ctx) -> str:
    f = {"upper": str.upper, "lower": str.lower}.get(ctx.case)
    if not f:
        return name
    # $i (loop index) and @s (string substitution) stay as they are
    return re.sub(r"[$@]\w+|[^$@]+", lambda m: m.group(0) if m.group(0)[0] in "$@" else f(m.group(0)), name)


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
    (r"@rnorm(?!\s*\()", "normal()"),
    (r"@runif(?!\s*\()", "uniform()"),
    (r"@date(?!\w|\s*\()", "ev_date()"),
    (r"@day", "$obsmicro"),
    (r"@weekday", "((weekday($obsmajor, $obsminor, $obsmicro) + 6) % 7 + 1)"),
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


# EViews matrix functions with one-to-one hansl names
MATRIX_FUNCS = [
    ("@inverse", "inv"), ("@transpose", "transp"), ("@det", "det"), ("@identity", "I"),
    ("@cholesky", "cholesky"), ("@eigenvalues", "eigensym"), ("@trace", "tr"),
    ("@rank", "rank"), ("@vec", "vec"), ("@rows", "rows"), ("@columns", "cols"),
    ("@getmaindiagonal", "diag"),
    # strings and dates (EViewsCompat helpers)
    ("@left", "ev_left"), ("@right", "ev_right"), ("@mid", "ev_mid"), ("@instr", "ev_instr"),
    ("@word", "ev_word"), ("@len", "strlen"), ("@length", "strlen"), ("@upper", "toupper"),
    ("@lower", "tolower"), ("@trim", "strstrip"), ("@ltrim", "strstrip"), ("@rtrim", "strstrip"),
    ("@replace", "strsub"), ("@val", "atof"), ("@dateval", "ev_dateval"), ("@datestr", "ev_datestr"),
    ("@isna", "missing"),
]
_MFUNC_RES = [(re.compile(re.escape(a) + r"\s*\(", re.IGNORECASE), b + "(") for a, b in MATRIX_FUNCS]


def _call_args(p: str, start: int) -> tuple[list[str], int]:
    """Split the arguments of a call whose '(' is at p[start]; return (args, end index after ')')."""
    depth, cur, args = 0, "", []
    for i in range(start, len(p)):
        ch = p[i]
        if ch == "(":
            depth += 1
            if depth == 1:
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                args.append(cur.strip())
                return args, i + 1
        elif ch == "," and depth == 1:
            args.append(cur.strip())
            cur = ""
            continue
        cur += ch
    raise ValueError("unbalanced parentheses")


def _matrix_funcs(p: str) -> str:
    """Functions that become operators or slices: @kronecker, @emult, @ediv, *extract."""
    forms = {
        "@kronecker": lambda a: f"({a[0]} ** {a[1]})",
        "@emult": lambda a: f"({a[0]} .* {a[1]})",
        "@ediv": lambda a: f"({a[0]} ./ {a[1]})",
        "@convert": lambda a: "{" + a[0] + "}",
        "@columnextract": lambda a: f"{a[0]}[,{a[1]}]",
        "@rowextract": lambda a: f"{a[0]}[{a[1]},]",
        "@subextract": lambda a: f"{a[0]}[{a[1]}:{a[3] if len(a) > 3 else 'rows(' + a[0] + ')'},"
                                 f"{a[2]}:{a[4] if len(a) > 4 else 'cols(' + a[0] + ')'}]",
        # distributions: EViews (x, parameters) -> hansl (distribution, parameters, x)
        "@ctdist": lambda a: f"cdf(t, {a[1]}, {a[0]})", "@dtdist": lambda a: f"pdf(t, {a[1]}, {a[0]})",
        "@qtdist": lambda a: f"invcdf(t, {a[1]}, {a[0]})",
        "@cchisq": lambda a: f"cdf(X, {a[1]}, {a[0]})", "@dchisq": lambda a: f"pdf(X, {a[1]}, {a[0]})",
        "@qchisq": lambda a: f"invcdf(X, {a[1]}, {a[0]})",
        "@cfdist": lambda a: f"cdf(F, {a[1]}, {a[2]}, {a[0]})", "@dfdist": lambda a: f"pdf(F, {a[1]}, {a[2]}, {a[0]})",
        "@qfdist": lambda a: f"invcdf(F, {a[1]}, {a[2]}, {a[0]})",
        "@rnorm": lambda a: "normal()", "@runif": lambda a: f"uniform({a[0]}, {a[1]})" if len(a) > 1 else "uniform()",
        "@rchisq": lambda a: f"randgen(X, {a[0]})", "@rtdist": lambda a: f"randgen(t, {a[0]})",
        # logical helpers
        "@recode": lambda a: f"(({a[0]}) ? ({a[1]}) : ({a[2]}))", "@iif": lambda a: f"(({a[0]}) ? ({a[1]}) : ({a[2]}))",
        "@nan": lambda a: f"(ok({a[0]}) ? ({a[0]}) : ({a[1]}))",
        "@inlist": lambda a: _inlist(a[0], a[1]),
        "@str": lambda a: f'sprintf("%g", {a[0]})', "@wcount": lambda a: f"nelem(strsplit({a[0]}))",
    }
    rx = re.compile(r"(@kronecker|@emult|@ediv|@convert|@columnextract|@rowextract|@subextract|@ctdist|@dtdist|@qtdist"
                    r"|@cchisq|@dchisq|@qchisq|@cfdist|@dfdist|@qfdist|@rnorm|@runif|@rchisq|@rtdist|@recode|@iif"
                    r"|@nan|@inlist|@str|@wcount)\s*(?=\()", re.IGNORECASE)
    while True:
        m = rx.search(p)
        if not m:
            return p
        args, end = _call_args(p, m.end())
        args = [_matrix_funcs(a) for a in args]
        p = p[:m.start()] + forms[m.group(1).lower()](args) + p[end:]


def _inlist(x: str, lst: str) -> str:
    """@inlist(x, "a b c") -> (x == a || x == b || x == c); strings are compared as strings."""
    items = lst.strip().strip('"').split()
    if not items:
        return "0"
    num = all(re.fullmatch(r"[-+]?\d+(\.\d*)?", i) for i in items)
    return "(" + " || ".join(f"{x} == {i}" if num else f'{x} == "{i}"' for i in items) + ")"


def _string_plus(e: str) -> str:
    """EViews joins strings with +: hansl uses ~ (only + at parenthesis depth 0, outside literals)."""
    out, depth, inq = [], 0, False
    for ch in e:
        if ch == '"':
            inq = not inq
        elif not inq:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "+" and depth == 0:
                ch = "~"
        out.append(ch)
    return "".join(out)


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
        if v.isdigit():
            ctx.args_used.add(int(v))
            return f"@ev_arg{v}"
        return f"${v}" if v in ctx.foreach_vars else f"@{safe_name(v, 's_')}"

    def plain_str(m):
        v = m.group(1)
        if v.isdigit():
            ctx.args_used.add(int(v))
            return f"ev_arg{v}"
        return v if v in ctx.foreach_vars else safe_name(v, "s_")
    p = re.sub(r"\{!(\w+)\}", lambda m: f"${safe_name(m.group(1), 'v_')}", p)
    p = re.sub(r"\{%(\w+)\}", braced_str, p)
    p = re.sub(r"(?<=[A-Za-z0-9_])!(\w+)", lambda m: f"${safe_name(m.group(1), 'v_')}", p)
    p = re.sub(r"!(\w+)", lambda m: safe_name(m.group(1), "v_"), p)
    p = re.sub(r"%(\w+)", plain_str, p)
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
            res = f"ev_resid({eq})" if ctx.equations.get(eq) in ("ls", "panel", "tsls", "binary", "ardl", "mlreg", "cointreg") \
                else apply_case(f"{eq}_resid", ctx)
            p = re.sub(r"(?<![A-Za-z0-9_])resid(?![A-Za-z0-9_])", res, p, flags=re.IGNORECASE)
        # matrix element m(i,j) -> m[i,j]
        for mt in ctx.matrices:
            p = re.sub(rf"(?<![A-Za-z0-9_.$]){re.escape(mt)}\s*\(\s*([^()]+)\)", rf"{mt}[\1]", p,
                       flags=re.IGNORECASE)
        # group element g(i) -> g[i]
        for g in ctx.groups:
            p = re.sub(rf"(?<![A-Za-z0-9_.$]){re.escape(g)}\s*\(\s*([^()-][^()]*)\)", rf"{g}[\1]", p)
        p = p.replace("<>", "!=")
        p = re.sub(r"\band\b", "&&", p, flags=re.IGNORECASE)
        p = re.sub(r"\bor\b", "||", p, flags=re.IGNORECASE)
        p = re.sub(r"\bnot\b", "!", p, flags=re.IGNORECASE)
        if condition:
            p = re.sub(r"(?<![<>!=])=(?!=)", "==", p)
            # x = na is a missing-value test in EViews
            p = re.sub(r"([\w.$\[\]]+)\s*==\s*NA\b", r"missing(\1)", p)
            p = re.sub(r"([\w.$\[\]]+)\s*!=\s*NA\b", r"!missing(\1)", p)
        if ctx.case != "keep":
            p = case_names(p, ctx)
        out.append(p)
    # matrix/string/distribution functions last (their hansl names must not be re-cased);
    # on the whole expression, since their arguments may be string literals
    p = _matrix_funcs("".join(out))
    for rx, dst in _MFUNC_RES:
        p = rx.sub(dst, p)
    return p


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
        if "(" in paren and (name.lower() in _FUNC_NAMES or name.startswith("ev_")):
            return m.group(0)
        return _case_ident(name, ctx) + paren
    return re.sub(r"(?<![A-Za-z0-9_$@.])([A-Za-z][A-Za-z0-9_]*)(?![A-Za-z0-9_])(\s*\(?)", fix, p)


def _case_ident(name: str, ctx: Ctx) -> str:
    if name in _KEEP_CASE or name in ctx.index_vars or name in ctx.foreach_vars \
            or name in ctx.scalars or name in ctx.strings or name.startswith("ev_") \
            or name in ctx.groups or name in ctx.equations or name in ctx.matrices:
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
        if ctx.panel and (translate_date(a) or translate_date(b)):
            # gretl panels have no calendar: the date range is left to the user
            out.append(f"# NOTE: date range {a} {b} not applied on the panel page "
                       f"(restrict with the time variable: smpl {ctx.panel[1]} >= ... --restrict)")
        else:
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
    op = _opts(opts)
    if "w" in op and not (ctx.panel or "cx" in op):
        wt = op.get("wtype", "istdev").lower()
        if "=" in sp:
            raise ValueError("weighted explicit equations are not supported")
        return [f'bundle {name} = ev_wls("{sp}", dataset, "{translate_expr(op["w"], ctx)}", "{wt}")']
    if ctx.panel or "cx" in op or "per" in op:
        # panel least squares: cross-section fixed/random effects, period fixed effects
        if "=" in sp:
            raise ValueError("explicit (nonlinear) equations on a panel page are not supported")
        cx = {"f": "fixed", "r": "random"}.get(op.get("cx", "")[:1].lower(), "none")
        per = 1 if op.get("per", "")[:1].lower() == "f" else 0
        if op.get("per", "")[:1].lower() == "r":
            raise ValueError("period random effects are not supported (use per=f)")
        ctx.equations[name] = "panel"
        return [f'bundle {name} = ev_panel("{sp}", dataset, "{cx}", {per})']
    cov = _ls_cov(opts)
    args = f'"{_spec(spec, ctx)}", dataset' + (f', "{cov}"' if cov else "")
    return [f"bundle {name} = ev_ls({args})"]


def _new_eq(name: str, kind: str, spec: str, ctx: Ctx) -> tuple[str, str]:
    name = translate_name(name, ctx)
    ctx.equations[name] = kind
    ctx.last_eq = name
    sp = _spec(spec, ctx)
    ctx.eq_dep[name] = sp.split()[0]
    return name, sp


def _tsls_call(name: str, opts: str | None, spec: str, ctx: Ctx) -> list[str]:
    if "@" not in spec:
        raise ValueError("tsls: give the instruments after @")
    if "=" in spec.split("@")[0]:
        raise ValueError("nonlinear TSLS (explicit equations) is not supported")
    name, sp = _new_eq(name, "tsls", spec.replace("@", " @ "), ctx)
    sp = re.sub(r"\s+", " ", sp)
    cov = _ls_cov(opts)
    return [f'bundle {name} = ev_tsls("{sp}", dataset' + (', "white"' if cov == "white" else "") + ")"]


def _binary_call(name: str, opts: str | None, spec: str, ctx: Ctx) -> list[str]:
    d = _opts(opts).get("d", "l").lower()[:1]
    if d not in ("l", "p", "n"):
        raise ValueError("binary: only d=l (logit) and d=p (probit) are supported")
    name, sp = _new_eq(name, "binary", spec, ctx)
    return [f'bundle {name} = ev_binary("{sp}", dataset, "{"logit" if d == "l" else "probit"}")']


def _ardl_call(name: str, opts: str | None, spec: str, ctx: Ctx) -> list[str]:
    op = _opts(opts)
    unknown = set(op) - {"deplags", "reglags", "ic", "trend"}
    if unknown:
        raise ValueError(f"ardl option {sorted(unknown)[0]}= not supported")
    ic = {"bic": "sic", "schwarz": "sic"}.get(op.get("ic", "aic").lower(), op.get("ic", "aic").lower())
    tr = {"c": "const", "none": "none", "const": "const", "linear": "linear", "trend": "linear"}.get(
        op.get("trend", "const").lower(), "const")
    name, sp = _new_eq(name, "ardl", spec.replace("@", " @ "), ctx)
    sp = re.sub(r"\s+", " ", sp)
    return [f'bundle {name} = ev_ardl("{sp}", dataset, {op.get("deplags", "4")}, {op.get("reglags", "4")}, '
            f'"{ic}", "{tr}")']


def _liml_call(name: str, opts: str | None, spec: str, ctx: Ctx) -> list[str]:
    if "@" not in spec:
        raise ValueError("liml: give the instruments after @")
    name, sp = _new_eq(name, "tsls", spec.replace("@", " @ "), ctx)
    sp = re.sub(r"\s+", " ", sp)
    return [f'bundle {name} = ev_tsls("{sp}", dataset, null, 0, 1)']


def _ml_call(kind: str):
    def call(name: str, opts: str | None, spec: str, ctx: Ctx) -> list[str]:
        op = _opts(opts)
        d = op.get("d", "").lower()[:1]
        p1, p2, m = "NA", "NA", None
        if kind == "ordered":
            m = {"": "ologit", "l": "ologit", "n": "oprobit"}.get(d)
        elif kind == "censored":
            if d not in ("", "n"):
                raise ValueError("censored: only normal errors (tobit) are supported")
            m = "tobit"
            p1 = op.get("l", "0") or "0"
            p2 = op.get("r", "NA") or "NA"
            if "t" in op:
                raise ValueError("truncated regression is not supported")
        elif kind == "count":
            m = {"": "poisson", "p": "poisson", "n": "negbin"}.get(d)
        elif kind == "qreg":
            m = "qreg"
            p1 = op.get("quant", "0.5")
        if not m:
            raise ValueError(f"{kind}: option d={d} not supported")
        name, sp = _new_eq(name, "mlreg", spec, ctx)
        return [f'bundle {name} = ev_mlreg("{sp}", dataset, "{m}", {p1}, {p2})']
    return call


def _gmm_call(name: str, opts: str | None, spec: str, ctx: Ctx) -> list[str]:
    op = _opts(opts)
    if "@" not in spec:
        raise ValueError("gmm: give the instruments after @")
    left, right = spec.split("@", 1)
    if op.get("cx", "").lower().startswith("fd") or "@dyn" in right.lower():
        # dynamic panel GMM (Arellano-Bond): y y(-1) ... x @ @dyn(y)
        toks = _spec(left, ctx).split()
        y = toks[0]
        p = sum(1 for t in toks[1:] if re.fullmatch(re.escape(y) + r"\(-\d+\)", t, re.IGNORECASE))
        xs = [t for t in toks[1:] if not re.fullmatch(re.escape(y) + r"\(-\d+\)", t, re.IGNORECASE)
              and t.lower() != "c"]
        two = 1 if "2" in op.get("gmm", "") or "2step" in (opts or "").lower() else 0
        per = 1 if op.get("per", "").lower().startswith("f") else 0
        name = translate_name(name, ctx)
        ctx.equations[name] = "dpanel"
        ctx.last_eq = name
        return [f'bundle {name} = ev_dpanel("{y}", "{" ".join(xs)}", dataset, {max(p, 1)}, {two}, {per})']
    # single equation GMM: a one-equation system (White weighting; HAC with instwgt=hac)
    name = translate_name(name, ctx)
    sp = _spec(left, ctx).split()
    inst = " ".join(t for t in _spec(right, ctx).split() if t.lower() != "c")   # a constant is always added
    hac = "0" if "hac" in (opts or "").lower() else "-1"
    nums = " ".join(str(i) for i in range(1, len(sp)))
    ctx.equations[name] = "system"
    ctx.last_eq = name
    return [f'bundle {name} = ev_system(defarray("{sp[0]}"), defarray("{" ".join(sp[1:])}"), '
            f'defarray("{nums}"), dataset, "gmm", "{inst}", 0, null, {hac})']


def _cointreg_call(name: str, opts: str | None, spec: str, ctx: Ctx) -> list[str]:
    op = _opts(opts)
    m = op.get("method", "fmols").lower()           # EViews default: FMOLS
    if m not in ("fmols", "dols"):
        raise ValueError(f"cointreg method={m} not supported (fmols, dols)")
    lead = op.get("lead", "1")
    lag = op.get("lag", "1")
    lead = lead if lead.isdigit() else "1"
    lag = lag if lag.isdigit() else "1"
    tr = {"none": "none", "const": "const", "linear": "linear", "c": "const"}.get(op.get("trend", "const").lower(), "const")
    name, sp = _new_eq(name, "cointreg", spec, ctx)
    return [f'bundle {name} = ev_cointreg("{sp}", dataset, "{m}", {lead}, {lag}, "{tr}")']


EQ_METHODS = {"ls": None, "arch": None, "tsls": _tsls_call, "binary": _binary_call, "ardl": _ardl_call,
              "liml": _liml_call, "ordered": _ml_call("ordered"), "censored": _ml_call("censored"),
              "count": _ml_call("count"), "qreg": _ml_call("qreg"), "gmm": _gmm_call, "cointreg": _cointreg_call}


def _arch_call(name: str, opts: str | None, spec: str, ctx: Ctx) -> list[str]:
    o = [x.strip().lower() for x in (opts or "1,1").split(",") if x.strip()]
    kv = dict(x.split("=", 1) for x in o if "=" in x)
    archm = kv.get("archm", "")
    if archm and archm not in ("var", "sd", "log"):
        raise ValueError("archm must be var, sd or log")
    thrsh = kv.get("thrsh", "")
    if thrsh and not thrsh.isdigit():
        raise ValueError("thrsh needs a number")
    unknown = [k for k in kv if k not in ("archm", "thrsh")]
    dist = "t" if "tdist" in o else ("ged" if "ged" in o else "")
    if unknown:
        raise ValueError(f"arch option {unknown[0]}= not supported")
    o = [x for x in o if "=" not in x and x not in ("tdist", "ged", "n")]
    model = "tarch" if any(x in ("t", "tarch") for x in o) else \
        ("egarch" if any(x in ("e", "egarch") for x in o) else "garch")
    nums = [x for x in o if re.fullmatch(r"\d+", x)]
    na, ng = (nums + ["1", "1"])[:2]          # EViews arch(ARCH order, GARCH order)
    name = translate_name(name, ctx)
    ctx.equations[name] = "arch"
    ctx.last_eq = name
    sp = _spec(spec, ctx)
    ctx.eq_dep[name] = sp.split()[0]
    hn, rn = apply_case(f"{name}_h", ctx), apply_case(f"{name}_resid", ctx)
    if model != "garch" or archm or thrsh or dist:
        # TARCH / EGARCH / ARCH-M through the gig package and EViewsCompat (EViews parameterisation)
        ctx.equations[name] = "garch"
        extra = ""
        if archm or thrsh or dist:
            extra = (f', "{archm}"' if archm else ", null") + (f", {thrsh}" if thrsh else ", -1") \
                + (f', "{dist}"' if dist else "")
            if not dist and not thrsh:
                extra = extra[: extra.rindex(", -1")]
        return [f'bundle ev_gb = ev_garch("{sp}", dataset, "{model}", {na}, {ng}, 1{extra})',
                "if ev_gb.failed",
                f'printf "Warning: {name} ({model.upper()}) did not converge; previous estimates kept\\n"',
                "else",
                f"bundle {name} = ev_gb",
                f'series {hn} = ev_garchseries({name}, "h")',
                f'series {rn} = ev_garchseries({name}, "resid")',
                "endif"]
    toks = sp.split()
    dep, regs = toks[0], ["const" if t.lower() == "c" else translate_expr(t, ctx) for t in toks[1:]]
    # gretl garch p q: p = GARCH order, q = ARCH order
    # EViews warns and continues when GARCH does not converge; so do we
    return [f"catch garch {ng} {na} ; {translate_expr(dep, ctx)} {' '.join(regs)} --quiet",
            "if $error",
            f'printf "Warning: {name} (GARCH) did not converge; previous estimates kept\\n"',
            "else",
            f"bundle {name} = _(coeff = $coeff, vcv = $vcv, lnl = $lnl)",
            f"series {hn} = $h",
            f"series {rn} = $uhat",
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
    # ips: gretl's adf on a panel prints the Im-Pesaran-Shin W_tbar test
    test = "adf" if "adf" in o or "ips" in o or not ({"kpss", "pp", "llc", "df", "ers", "np"} & o.keys()) else None
    det = "--ct" if "trend" in o else ("--nc" if "none" in o else "--c")
    diff = " --difference" if o.get("dif", "0") not in ("", "0") else ""
    lag = o.get("maxlag") or o.get("lag") or "4"
    x = translate_name(series, ctx)
    info = o.get("info", "")
    down = {"aic": " --test-down=AIC", "sic": " --test-down=BIC", "bic": " --test-down=BIC",
            "hqc": " --test-down=tstat", "tstat": " --test-down=tstat"}.get(info, "")
    if test == "adf":
        return [f"adf {lag} {x} {det}{diff}{down}"]
    if "pp" in o:
        # Phillips-Perron (Bartlett kernel, Newey-West automatic bandwidth by default)
        bw = o.get("bw") or o.get("band") or ""
        bw = bw if re.fullmatch(r"\d+(\.\d+)?", bw) else "-1"
        d = "ct" if "trend" in o else ("nc" if "none" in o else "c")
        dif = 1 if o.get("dif", "0") not in ("", "0") else 0
        return [f'bundle {x}_pp = ev_pp("{x}", dataset, "{d}", {bw}, {dif})']
    if "kpss" in o:
        return [f"kpss {o.get('lag', '-1')} {x}" + (" --trend" if "trend" in o else "")]
    if "llc" in o:
        # a sample left with one cross-section is a time series in gretl: plain ADF
        return ["if $datatype == 3",
                f"levinlin {lag} {x}" + (" --ct" if "trend" in o else ""),
                "else",
                f"adf {lag} {x} {det}{diff}{down}",
                "endif"]
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


def _system_estimate(o: str, method: str, ctx: Ctx, opts: str | None = None) -> list[str]:
    sysd = ctx.systems.get(o)
    if not sysd or not sysd["eqs"]:
        raise ValueError(f"system {o} has no equations")
    hac = "0" if "hac" in (opts or "").lower() else "-1"
    q = lambda arr: ", ".join(f'"{a}"' for a in arr)
    inst = _spec(sysd["inst"], ctx) if sysd["inst"] else ""
    try:
        for ln in sysd["eqs"]:
            _linear_equation(program_vars(ln, ctx))
    except ValueError as e:
        if "linear" not in str(e):
            raise
        # nonlinear in the coefficients: Gauss-Newton / Levenberg-Marquardt estimator
        eqs = []
        for ln in sysd["eqs"]:
            lhs, rhs = program_vars(ln, ctx).split("=", 1)
            if ctx.case != "keep":
                lhs, rhs = case_names(lhs, ctx), case_names(rhs, ctx)
            eqs.append(f"{lhs.strip()} = {rhs.strip()}")
        ctx.equations[o] = "system"
        ctx.last_eq = o
        return [f"strings ev_se = defarray({q(eqs)})",
                f'bundle {o} = ev_nlsystem(ev_se, dataset, "{method}", "{inst}", 1, {hac})',
                f'{o}.name = "{o.upper()}"',
                f"ev_sysprint(&{o})"]
    deps, xs, cs, txt = [], [], [], []
    for ln in sysd["eqs"]:
        d, x, c = _linear_equation(program_vars(ln, ctx))
        deps.append(case_names(d, ctx) if ctx.case != "keep" else d)
        xs.append(_spec(x, ctx))
        cs.append(c)
        txt.append(re.sub(r"\s+", "", ln).upper())
    ctx.equations[o] = "system"
    ctx.last_eq = o
    return [f"strings ev_sd = defarray({q(deps)})",
            f"strings ev_sx = defarray({q(xs)})",
            f"strings ev_sc = defarray({q(cs)})",
            f"strings ev_st = defarray({q(txt)})",
            f'bundle {o} = ev_system(ev_sd, ev_sx, ev_sc, dataset, "{method}", "{inst}", 1, ev_st, {hac})',
            f'{o}.name = "{o.upper()}"',
            f"ev_sysprint(&{o})"]


def _fiml_estimate(o: str, ctx: Ctx) -> list[str]:
    """FIML: gretl's system command at the top level, then ev_sysfrom."""
    sysd = ctx.systems[o]
    try:
        for ln in sysd["eqs"]:
            _linear_equation(program_vars(ln, ctx))
    except ValueError:
        raise ValueError("FIML needs equations linear in c(i); use sur or 3sls for nonlinear systems")
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
    op = _opts(opts)
    stochastic = op.get("s", "d").lower().startswith("s")
    reps = op.get("r", "100") if stochastic else "0"
    suf = md.get("suffix", "_0")
    ovr = md.get("overrides", []) if suf != "_0" else []
    items = [f'suffix = "{suf}"', f"addfactors = {int(md.get('addf', False))}", f"reps = {reps}"]
    if ovr:
        items.insert(0, f"overrides = defarray({q(ovr)})")
    out = [f"bundles ev_mb = defarray({', '.join(md['eqs'])})" if md["eqs"] else "bundles ev_mb = array(0)",
           f"strings ev_mi = defarray({q(ids)})" if ids else "strings ev_mi = array(0)",
           f"bundle ev_mo = _({', '.join(items)})",
           f"bundle {o} = ev_modelsolve(ev_mb, ev_mi, dataset, {dynamic}, 0, ev_mo)"]
    out += [f"series {n}{suf} = ev_modelseries({o}, {k})" for k, n in enumerate(names, 1)]
    if stochastic:
        out += [f'series {n}{suf}m = ev_modelseries({o}, {k}, "mean")' for k, n in enumerate(names, 1)]
        out += [f'series {n}{suf}s = ev_modelseries({o}, {k}, "sd")' for k, n in enumerate(names, 1)]
    return out


def svar_text(lines: list[str], n: int):
    """EViews text restrictions -> ('ab', A, B) pattern matrices (None = estimated)
    or ('lr', ordering) for long-run zeros @lrI(@uJ) = 0."""
    lines = [ln.strip() for ln in lines if ln.strip()]
    if lines and all(re.match(r"(?i)@lr\d", ln) for ln in lines):
        zero = set()
        for ln in lines:
            m = re.fullmatch(r"(?i)@lr(\d+)\(\s*@u(\d+)\s*\)\s*=\s*0", ln)
            if not m:
                raise ValueError(f"long-run restriction not understood: {ln}")
            zero.add((int(m.group(1)), int(m.group(2))))
        if len(zero) != n * (n - 1) // 2:
            raise ValueError(f"long-run restrictions: exactly {n * (n - 1) // 2} zeros are needed")
        for perm in itertools.permutations(range(1, n + 1)):
            pos = {v: i for i, v in enumerate(perm)}
            if all(pos[j] > pos[i] for i, j in zero):
                return "lr", list(perm)
        raise ValueError("long-run zeros must form a recursive (triangular) pattern")
    A = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    B = [[0.0] * n for _ in range(n)]
    seen = set()
    for ln in lines:
        m = re.fullmatch(r"(?i)@e(\d+)\s*=\s*(.+)", ln)
        if not m:
            raise ValueError(f"restriction not understood: {ln}")
        i = int(m.group(1)) - 1
        for t in _split_terms(m.group(2).replace(" ", "")):
            sign = -1.0 if t.startswith("-") else 1.0
            t = t.lstrip("+-")
            mm = re.fullmatch(r"(?i)(?:(c\(\d+\)|[\d.]+)\*)?@([eu])(\d+)", t)
            if not mm:
                raise ValueError(f"term not understood: {t}")
            coef, kind, j = mm.group(1), mm.group(2).lower(), int(mm.group(3)) - 1
            if coef and coef.lower().startswith("c("):
                if coef.lower() in seen:
                    raise ValueError(f"{coef} appears twice: equality restrictions are not supported")
                seen.add(coef.lower())
                val = None
            else:
                val = sign * float(coef) if coef else sign
            if kind == "e":
                A[i][j] = None if val is None else -val
            else:
                B[i][j] = val
    return "ab", A, B


def _mat_literal(M) -> str:
    return "{" + "; ".join(", ".join("NA" if v is None else repr(float(v)) for v in row) for row in M) + "}"


def svar_text_commands(var: str, lines: list[str], n: int) -> list[str]:
    res = svar_text(lines, n)
    if res[0] == "lr":
        return [f"ev_svar_lr(&{var}, 0, {{{', '.join(map(str, res[1]))}}})"]
    return [f"matrix ev_A = {_mat_literal(res[1])}", f"matrix ev_B = {_mat_literal(res[2])}",
            f"ev_svar(&{var}, ev_A, ev_B)"]


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
            return _system_estimate(o, meth_map[ml], ctx, opts)
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
        rtype = op.get("rtype", "")
        if rtype in ("text", "lrtext"):
            tname = translate_name(args.split()[0], ctx) if args.split() else ""
            if tname not in ctx.texts:
                raise ValueError("svar(rtype=text) needs a text object with the restrictions")
            n = len(ctx.var_endo.get(o, [])) or 0
            if not n:
                raise ValueError("svar: the VAR is not known here")
            return svar_text_commands(o, ctx.texts[tname], n)
        if rtype == "patlr":
            # long-run pattern matrix: zeros restricted, NA free -> recursive ordering
            name = translate_name(op.get("namelr", ""), ctx)
            if name not in ctx.matrix_values:
                raise ValueError("svar(rtype=patlr) needs namelr= a filled pattern matrix")
            vals, (r, c) = ctx.matrix_values[name], ctx.matrices[name]
            lines = [f"@lr{i + 1}(@u{j + 1}) = 0" for i in range(r) for j in range(c)
                     if vals[i][j] not in (None,) and float(vals[i][j]) == 0.0]
            return svar_text_commands(o, lines, r)
        if "lr" in op or "bq" in op or rtype.startswith("lr"):
            return [f"ev_svar_lr(&{o})"]
        a, b = op.get("namea"), op.get("nameb")
        if not a or not b:
            raise ValueError("svar: give rtype=patsr, namea=A, nameb=B (pattern matrices) or lr")
        return [f"ev_svar(&{o}, {translate_name(a, ctx)}, {translate_name(b, ctx)})"]
    if o in ctx.tables:
        return _table_method(o, ml, opts, args, ctx)
    if o in ctx.texts and ml == "append":
        ctx.texts[o].append(args.strip())
        return [f"# text {o}: {args.strip()}"]
    if o in ctx.matrices and ml == "fill":
        r, c = ctx.matrices[o]
        vals = [v.strip() for v in args.split(",") if v.strip()]
        vals = ["NA" if v.lower() in ("na", "nan") else translate_expr(v, ctx) for v in vals]
        if len(vals) != r * c:
            raise ValueError(f"fill: {o} needs {r * c} values")
        byrow = _opts(opts).get("b", "c").lower().startswith("r")
        nums = [None if v == "NA" else v for v in vals]
        grid = [[nums[i * c + j] if byrow else nums[j * r + i] for j in range(c)] for i in range(r)]
        ctx.matrix_values[o] = grid
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
        if ml == "scenario":
            nm = args.strip().strip('"')
            if nm.lower().startswith("base"):
                md["suffix"] = "_0"
            else:
                m = re.search(r"(\d+)", nm)
                md["suffix"] = f"_{m.group(1) if m else 1}"
            return [f"# model {o}: scenario {nm} (solution suffix {md['suffix']})"]
        if ml == "override":
            md["overrides"] += [translate_name(x, ctx) for x in args.split()]
            return [f"# model {o}: override {args.strip()}"]
        if ml in ("addassign", "addinit"):
            md["addf"] = True
            out = []
            for e in md["eqs"]:
                base = _dep_base(ctx.eq_dep[e])
                out.append(f"series {base}_a = " + (f"ev_eqres({e}, dataset)" if ml == "addinit" else "0"))
            return out
        raise ValueError(f"model method .{meth} not supported")
    if ml == "coint" and re.search(r"(?i)method\s*=\s*(eg|po)", opts or ""):
        op = _opts(opts)
        if o in ctx.groups:
            names = " ".join(ctx.groups[o])
        else:
            raise ValueError("coint(method=eg|po) needs a group of series")
        d = {"none": "nc", "const": "c", "linear": "ct"}.get(op.get("trend", "const").lower(), "c")
        lagv = op.get("lag", "a")
        lagv = lagv if lagv.isdigit() else "-1"
        ml_ = op.get("maxlag", "-1")
        ml_ = ml_ if ml_.isdigit() else "-1"
        return [f'bundle {o}_coint = ev_cointeg("{names}", dataset, "{op["method"].lower()}", "{d}", {lagv}, {ml_})']
    if ml == "seas":
        k = (opts or "m").strip().lower()[:1] or "m"
        if k not in ("m", "a"):
            raise ValueError("seas: m (multiplicative) or a (additive)")
        outs = [translate_name(n, ctx) for n in args.split()]
        if not outs:
            raise ValueError("seas needs the name of the adjusted series")
        if len(outs) > 1:
            return [f"series {outs[1]} = NA", f'series {outs[0]} = ev_seasadj({o}, "{k}", &{outs[1]})']
        return [f'series {outs[0]} = ev_seasadj({o}, "{k}")']
    if ml in ("x13", "x12"):
        # X-13ARIMA-SEATS through gretl's deseas() (needs the x13as program set up in gretl)
        op = opts or ""
        m = re.search(r'(?i)save\s*=\s*"?([^",)]*)"?', op)
        want = [w.lower() for w in (m.group(1).split() if m else ["d11"])]
        bad = [w for w in want if w not in ("d10", "d11")]
        if bad:
            raise ValueError(f"x13 save={bad[0]}: only d11 (adjusted) and d10 (seasonal factors) are available")
        base = translate_name(args.strip(), ctx) if args.strip() else o
        d11, d10 = apply_case(f"{base}_d11", ctx), apply_case(f"{base}_d10", ctx)
        out = [f"series {d11} = deseas({o})"]
        if "d10" in want:
            out.append(f"series {d10} = min({o}) > 0 ? {o} / {d11} : {o} - {d11}")
        return out
    if ml == "tramoseats":
        raise ValueError("TRAMO-SEATS needs the tramo program, which is not installed; use x.x13 or x.seas(m)")
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
    if EQ_METHODS.get(ml) and ctx.equations.get(o) not in ("var", "vecm", "system", "model"):
        return EQ_METHODS[ml](obj, opts, args, ctx)
    # equation tests (least squares equations)
    if ml in ("hettest", "white", "archtest") and ctx.equations.get(o, "ls") == "ls":
        op = _opts(opts)
        ty = "white" if ml == "white" else ("arch" if ml == "archtest" else op.get("type", "bpg").lower())
        nl = op.get("lags") or (opts.strip() if ml == "archtest" and opts and opts.strip().isdigit() else "1")
        if ty not in ("bpg", "harvey", "glejser", "arch", "white"):
            raise ValueError(f"hettest type {ty} not supported")
        return [f'bundle {o}_het = ev_hettest({o}, "{ty}", {nl})']
    if ml in ("correlogram", "correlsq") and ctx.equations.get(o, "ls") in ("ls", "tsls", "ardl", "cointreg"):
        k = (opts or args or "12").strip() or "12"
        return [f"matrix {o}_corr = ev_rescorr({o}, {k}, {int(ml == 'correlsq')})"]
    if ml == "ubreak" and ctx.equations.get(o, "ls") == "ls":
        t = (opts or "15").strip() or "15"
        return [f"bundle {o}_ubreak = ev_ubreak({o}, {float(t) / 100:g})"]
    if ml == "varinf" and ctx.equations.get(o, "ls") == "ls":
        return [f"matrix {o}_vif = ev_vif({o})"]
    if ml in ("ranhaus", "fixedtest") and ctx.equations.get(o) == "panel":
        return [f"bundle {o}_ptest = ev_paneltests({o}.spec, dataset)"]
    if ml == "cause" and o in ctx.groups:
        m = re.match(r"\s*(\d+)", opts or "")
        return [f'matrix {o}_cause = ev_cause("{" ".join(ctx.groups[o])}", dataset, {m.group(1) if m else 2})']
    if ml == "reset" and ctx.equations.get(o, "ls") == "ls":
        n = (opts or "1").strip() or "1"
        return [f"bundle {o}_reset = ev_reset({o}, {n})"]
    if ml == "chow" and ctx.equations.get(o, "ls") == "ls":
        f = 1 if "f" in [x.strip().lower() for x in (opts or "").split(",")] else 0
        dates = " ".join(translate_date(d) or d for d in args.split())
        if not dates:
            raise ValueError("chow needs a breakpoint date")
        return [f'bundle {o}_chow = ev_chow({o}, "{dates}", {f})']
    if ml in ("testadd", "testdrop") and ctx.equations.get(o, "ls") == "ls":
        names = _spec(args, ctx)
        if ml == "testadd":
            return [f'bundle {o}_test = ev_testadd({o}, dataset, "{names}")']
        return [f'bundle {o}_test = ev_testdrop({o}, "{names}")']
    if ml == "rls" and ctx.equations.get(o, "ls") == "ls":
        what = (opts or "c").strip().lower()[:1] or "c"
        if what not in ("c", "q", "r"):
            raise ValueError("rls: c (CUSUM), q (CUSUM of squares) or r (recursive residuals)")
        return [f"bundle {o}_rls = ev_rls({o})", f'ev_rlsplot({o}_rls, "{what}"{_plot_file_arg(ctx)})']
    if ml in ("boundstest", "cointrep") and ctx.equations.get(o) == "ardl":
        return [f"ev_boundsprint(&{o})"]
    if ml == "wald":
        return [f'bundle {o}_wald = ev_wald({o}, "{args.strip()}")']
    if ml == "auto":
        return [f"bundle {o}_diag = ev_diag({o}, {(opts or '2').strip()})"]
    if ml == "jbera" and ctx.equations.get(o) not in ("var", "vecm"):
        return [f"bundle {o}_diag = ev_diag({o})"]
    if ml in ("output", "results", "display", "spec"):
        kind = ctx.equations.get(o)
        if kind == "arch":
            raise ValueError("output of a GARCH(p,q) equation: estimated with gretl's garch command")
        return [{"vecm": f"ev_vecprint(&{o})", "var": f"ev_varprint(&{o})", "panel": f"ev_panelprint(&{o})",
                 "binary": f"ev_binaryprint(&{o})", "ardl": f"ev_ardlprint(&{o})",
                 "mlreg": f"ev_mlprint(&{o})", "cointreg": f"ev_coefprint(&{o})", "dpanel": f"ev_coefprint(&{o})",
                 "system": f"ev_sysprint(&{o})",
                 "garch": f"ev_garchprint(&{o})"}.get(kind, f"ev_print(&{o})")]
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
            iop = [x.strip().lower() for x in (opts or "").split(",") if x.strip()]
            iod = _opts(opts)
            if ctx.equations.get(o) == "var" and (iod.get("imp", "").startswith("gen") or "a" in iop
                                                 or iod.get("se", "").startswith("boot")):
                kind = "gen" if iod.get("imp", "").startswith("gen") else "chol"
                reps = iod.get("rep", "100") if iod.get("se", "").startswith("boot") else "0"
                return [f'bundle {o}_irf = ev_varimpulse({o}, {h}, "{kind}", {int("a" in iop)}, {reps}, 0.95)']
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
        if ctx.equations.get(o) == "var":
            if ml == "white":
                return [f"bundle {o}_white = ev_varwhite({o})"]
            if ml == "makemodel":
                mname = translate_name(args.split()[0] if args.strip() else (opts or f"{o}_model").strip(), ctx)
                ctx.models[mname] = {"eqs": [], "ids": [], "suffix": "_0", "overrides": [], "addf": False}
                ctx.equations[mname] = "model"
                out = [f"bundles ev_vm_{o} = ev_var2eqs({o}, dataset)"]
                for k, nm in enumerate(ctx.var_endo.get(o, []), 1):
                    e = f"{o}_eq{k}"
                    out.append(f"bundle {e} = ev_vm_{o}[{k}]")
                    ctx.eq_dep[e] = nm
                    ctx.equations[e] = "ls"
                    ctx.models[mname]["eqs"].append(e)
                return out
            if ml == "arroots":
                return [f"matrix {o}_roots = ev_varroots({o})"]
            if ml == "arlm":
                m = re.match(r"\s*(\d+)", opts or args or "")
                return [f"matrix {o}_lm = ev_varlm({o}, {m.group(1) if m else 2})"]
            if ml == "jbera":
                f = _opts(opts).get("factor", "chol").lower()
                if not f.startswith("chol"):
                    raise ValueError("jbera: only factor=chol (Lutkepohl) is supported")
                return [f"bundle {o}_norm = ev_varnorm({o})"]
            if ml == "forecast":
                op = [x.strip().lower() for x in (opts or "").split(",") if x.strip()]
                dyn = 0 if ("s" in op or "static" in op) else 1
                suf = args.strip() or "_f"
                out = [f"bundle {o}_fc = ev_varfcast({o}, dataset, {dyn})"]
                for k, nm in enumerate(ctx.var_endo.get(o, []), 1):
                    base = re.sub(r"\W+", "_", nm).strip("_")
                    out.append(f"series {base}{suf} = ev_varfseries({o}_fc, {k})")
                return out
        raise ValueError(f"VAR view .{meth} not supported")
    if ml in ("makeresid", "makeresids") and ctx.equations.get(o) in ("ls", "panel", "tsls", "binary", "ardl", "mlreg", "cointreg"):
        return [f"series {translate_name(args.split()[0], ctx)} = ev_resid({o})"]
    if ml in ("makeresid", "makeresids") and ctx.equations.get(o) in ("arch", "garch"):
        return [f"series {translate_name(args.split()[0], ctx)} = {apply_case(o + '_resid', ctx)}"]
    if ml == "makegarch" and ctx.equations.get(o) in ("arch", "garch"):
        return [f"series {translate_name(args.split()[0], ctx)} = {apply_case(o + '_h', ctx)}"]
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
            ctx.panel = None
            return save_cur + body + ["scalar ev_N = $nobs"]
        if word == "pageselect":
            new = rest.split()[0]
            if new not in ctx.pages:
                raise ValueError(f"unknown page {new}")
            ctx.page = new
            ctx.panel = ctx.page_panel.get(new)
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

    if word == "pagestruct":
        # pagestruct id @date(t) -> panel: unit and time variables
        m = re.fullmatch(r"(?i)pagestruct(?:\([^)]*\))?\s+(\w+)\s+@date(?:var)?\s*\(\s*(\w+)\s*\)", s)
        if not m:
            raise ValueError("pagestruct: use pagestruct id @date(timevar)")
        uid, tv = translate_name(m.group(1), ctx), translate_name(m.group(2), ctx)
        ctx.panel = (uid, tv)
        ctx.page_panel[ctx.page] = ctx.panel
        return [f"setobs {uid} {tv} --panel-vars", "scalar ev_N = $nobs"]
    if word == "pageunstack":
        return _pageunstack(cmd_opts, rest, ctx)
    if word == "pagestack":
        return _pagestack(cmd_opts, rest, ctx)

    if word in ("matrix", "vector", "rowvector", "sym", "coef"):
        m = re.fullmatch(r"(?i)(\w+)\s*(?:\(\s*([^,()]+?)\s*(?:,\s*([^()]+?)\s*)?\))?\s+(\w+)\s*(?:=\s*(.+))?", s)
        if not m:
            raise ValueError(f"{word}: use {word}(size) name [= expression]")
        _, r, c, name, expr = m.groups()
        name = translate_name(name, ctx)
        if word in ("vector", "coef"):
            r, c = r or "1", "1"
        elif word == "rowvector":
            r, c = "1", r or "1"
        elif word == "sym":
            c = r
        dims = (int(r), int(c)) if r and c and r.isdigit() and c.isdigit() else (None, None)
        ctx.matrices[name] = dims
        if expr is None:
            if not (r and c):
                raise ValueError(f"{word}: give the size")
            return [f"matrix {name} = zeros({translate_expr(r, ctx)}, {translate_expr(c, ctx)})"]
        e = translate_expr(expr, ctx)
        if r and c and re.fullmatch(r"[-+]?[\d.]+(e[-+]?\d+)?|NA", e.strip(), re.IGNORECASE):
            return [f"matrix {name} = ones({translate_expr(r, ctx)}, {translate_expr(c, ctx)}) * {e}"]
        return [f"matrix {name} = {e}"]
    if word == "stom":
        a = [x.strip() for x in _call_args(s, s.index("("))[0]]
        src, dst = translate_name(a[0], ctx), translate_name(a[1], ctx)
        ctx.matrices[dst] = (None, None)
        return [f"matrix {dst} = {{{src}}}"]
    if word == "mtos":
        a = [x.strip() for x in _call_args(s, s.index("("))[0]]
        src, dst = translate_name(a[0], ctx), translate_name(a[1], ctx)
        if dst in ctx.groups:
            return [f"series {g} = {src}[,{j}]" for j, g in enumerate(ctx.groups[dst], 1)]
        return [f"series {dst} = {src}"]
    if word == "table":
        m = re.fullmatch(r"(?i)table\s*(?:\(\s*([^,()]+?)\s*,\s*([^()]+?)\s*\))?\s+(\w+)", s)
        if not m:
            raise ValueError("table: use table(rows, cols) name")
        r, c, name = m.groups()
        name = translate_name(name, ctx)
        ctx.tables.add(name)
        return [f"bundle {name} = ev_table({translate_expr(r or '1', ctx)}, {translate_expr(c or '1', ctx)})"]
    if word == "copy":
        return _copy(cmd_opts, rest, ctx)
    if word == "text":
        name = translate_name(rest.split()[0], ctx)
        ctx.texts[name] = []
        return [f"# text object {name}"]
    if word == "model":
        name = translate_name(rest.split()[0], ctx) if rest else "model01"
        ctx.models[name] = {"eqs": [], "ids": [], "suffix": "_0", "overrides": [], "addf": False}
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
    if word == "exitloop":
        return ["break"]
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
            pv = program_vars(n.strip(), ctx)
            n = pv if pv in ctx.scalars or pv in ctx.strings else translate_name(n, ctx)
            if n in ctx.tables:
                res.append(f"ev_tprint({n})")
                continue
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
        if EQ_METHODS.get(meth.lower()):
            return EQ_METHODS[meth.lower()](name, opts, spec, ctx)
        raise ValueError(f"estimation method {meth} not supported")
    m = re.fullmatch(r"(ls|tsls|binary|ardl|liml|ordered|censored|count|qreg|gmm|cointreg)(?:\(([^)]*)\))?\s+(.+)",
                     s, flags=re.IGNORECASE)
    if m:
        ctx.eq_counter += 1
        fn = EQ_METHODS.get(m.group(1).lower()) or _ls_call
        return fn(f"eq_untitled{ctx.eq_counter}", m.group(2), m.group(3), ctx)

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
        if elem is not None and translate_name(name, ctx) in ctx.tables:
            ij = [translate_expr(x, ctx) for x in _call_args("(" + elem + ")", 0)[0]]
            if len(ij) != 2:
                raise ValueError("table cells need two indices: t(i, j)")
            return [_table_set(translate_name(name, ctx), ij[0], ij[1], expr, ctx)]
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
            return [f"string {v} = {_string_plus(translate_expr(expr, ctx))}"]
        if name in ctx.scalars:
            return [f"{name} = {translate_expr(expr, ctx)}"]
        if translate_name(name, ctx) in ctx.matrices:
            return [f"matrix {translate_name(name, ctx)} = {translate_expr(expr, ctx)}"]
        return [f"series {translate_name(name, ctx)} = {translate_expr(expr, ctx)}"]

    raise ValueError("unsupported statement")


def _pageunstack(cmd_opts: str, rest: str, ctx: Ctx) -> list[str]:
    """pageunstack(namepat="*_?", page=name) id time @ series... -> one series per unit on a new page."""
    if not ctx.panel:
        raise ValueError("pageunstack needs a panel page (pagestruct first)")
    op = {}
    for k, v in re.findall(r'(\w+)\s*=\s*("[^"]*"|[^,]+)', cmd_opts or ""):
        op[k.lower()] = v.strip().strip('"')
    pat = op.get("namepat", "*?")
    new = op.get("page") or f"untitled{len(ctx.pages) + 1}"
    left, _, right = rest.partition("@")
    ids = left.split()
    if not ids or not right.split():
        raise ValueError("pageunstack: give id [time] @ series")
    uid = translate_name(ids[0], ctx)
    series = [translate_name(x, ctx) for x in right.split()]
    ctx.need_pages = True
    # the whole panel is unstacked (a restricted sample may no longer be a panel)
    out = ["smpl full", f"matrix ev_uid = ev_panelids({uid})"]
    for k, x in enumerate(series, 1):
        out.append(f"matrix ev_u{k} = ev_unstack({x})")
    tv = ctx.panel[1]
    out.append(f"matrix ev_ut = ev_unstack({tv})[,1]")
    out += ["string ev_pagedir = $dotdir", "smpl full", f'store "@ev_pagedir/{ctx.page}.gdtb"',
            "scalar ev_T = rows(ev_ut)", "nulldata ev_T --preserve",
            f"series {tv} = ev_ut    # time variable of the panel (the page is undated)"]
    for k, x in enumerate(series, 1):
        nm = pat.replace("*", x).replace("?", "%g")
        out += [f"loop ev_j = 1..cols(ev_u{k})",
                f'string ev_nm = sprintf("{nm}", ev_uid[ev_j])',
                f"series @ev_nm = ev_u{k}[,ev_j]",
                "endloop"]
    ctx.pages.add(new)
    ctx.page = new
    ctx.panel = None
    return out + ["scalar ev_N = $nobs"]


def _is_string_expr(expr: str, ctx: Ctx) -> bool:
    e = expr.strip()
    return '"' in e or e.startswith("%") or bool(re.match(
        r"(?i)@(left|right|mid|word|str|upper|lower|trim|ltrim|rtrim|replace|datestr)\s*\(", e))


def _table_set(t: str, i: str, j: str, expr: str, ctx: Ctx) -> str:
    if _is_string_expr(expr, ctx):
        return f"ev_tset(&{t}, {i}, {j}, {_string_plus(translate_expr(expr, ctx))})"
    return f"ev_tsetnum(&{t}, {i}, {j}, {translate_expr(expr, ctx)})"


def _col_number(c: str) -> str:
    c = c.strip()
    if re.fullmatch(r"[A-Za-z]{1,2}", c):
        n = 0
        for ch in c.upper():
            n = n * 26 + ord(ch) - 64
        return str(n)
    return c


def _table_method(t: str, ml: str, opts: str | None, args: str, ctx: Ctx) -> list[str]:
    if ml == "setcell":
        a = _call_args("(" + (opts or "") + ")", 0)[0] if opts else [x.strip() for x in args.split(",")]
        if len(a) < 3:
            raise ValueError("setcell needs row, column and value")
        return [_table_set(t, translate_expr(a[0], ctx), _col_number(a[1]), a[2], ctx)]
    if ml == "setwidth":
        cols = (opts or "").strip()
        w = args.strip() or "10"
        if ":" in cols:
            a, b = cols.split(":", 1)
            return [f"ev_twidth(&{t}, {k}, {w})" for k in range(int(_col_number(a)), int(_col_number(b)) + 1)]
        return [f"ev_twidth(&{t}, {_col_number(cols or '1')}, {w})"]
    if ml == "save":
        fmt = _opts(opts).get("t", "csv").lower()
        fmt = {"txt": "txt", "text": "txt", "csv": "csv", "html": "html"}.get(fmt)
        if not fmt:
            raise ValueError("table save: t=csv, txt or html (rtf/pdf are not supported)")
        f = args.strip().strip('"') or t
        if not re.search(r"\.\w+$", f):
            f += "." + fmt
        return [f'ev_tsave({t}, "{f}", "{fmt}")']
    if ml in ("display", "show", "output", "print"):
        return [f"ev_tprint({t})"]
    if ml in ("setjust", "setformat", "setlines", "setfont", "setfillcolor", "settextcolor", "title", "setmerge",
              "setindent", "deleterow", "deletecol", "insertrow", "insertcol"):
        raise Ignored("table formatting")
    raise ValueError(f"table method .{ml} not supported")


_COPY_METHODS = {"a": "a", "s": "s", "f": "f", "l": "l", "x": "x", "n": "n", "r": "r", "d": "d", "i": "i"}


def _copy(cmd_opts: str, rest: str, ctx: Ctx) -> list[str]:
    """copy [(c=method)] [page\\]src [[page\\]dest]: objects, and series between pages with frequency conversion."""
    toks = rest.split()
    if not toks or len(toks) > 2:
        raise ValueError("copy: give a source and (optionally) a destination")
    if any("*" in t or "?" in t for t in toks):
        raise ValueError("copy with wildcards is not supported")

    def split(t):
        if "\\" in t:
            pg, nm = t.split("\\", 1)
            return pg, nm
        return None, t
    sp, sn = split(toks[0])
    dp, dn = split(toks[1]) if len(toks) > 1 else (None, sn)
    sp = sp if sp else ctx.page
    dp = dp if dp else ctx.page
    sn, dn = translate_name(sn, ctx), translate_name(dn, ctx)
    op = _opts(cmd_opts)
    meth = op.get("c", "").lower()[:1]
    if meth and meth not in _COPY_METHODS:
        raise ValueError(f"copy(c={op.get('c')}): quadratic/cubic conversions are not supported (use a, s, f, l, x, n, r, d, i)")
    if sp == ctx.page and dp == ctx.page:
        # objects within the page
        if sn in ctx.equations:
            ctx.equations[dn] = ctx.equations[sn]
            return [f"bundle {dn} = {sn}"]
        if sn in ctx.matrices:
            ctx.matrices[dn] = ctx.matrices[sn]
            return [f"matrix {dn} = {sn}"]
        if sn in ctx.tables:
            ctx.tables.add(dn)
            return [f"bundle {dn} = {sn}"]
        if sn in ctx.groups:
            ctx.groups[dn] = list(ctx.groups[sn])
            ctx.group_page[dn] = ctx.page
            return [f"list {dn} = {sn}"]
        return [f"series {dn} = {sn}"]
    for pg in (sp, dp):
        if pg not in ctx.pages:
            raise ValueError(f"unknown page {pg}")
    ctx.need_pages = True
    marg = f', "{meth}"' if meth else ""
    out = ["string ev_pagedir = $dotdir", "scalar ev_s1 = $t1", "scalar ev_s2 = $t2", "smpl full",
           f'store "@ev_pagedir/{ctx.page}.gdtb"']
    if sp != ctx.page:
        out.append(f'open "@ev_pagedir/{sp}.gdtb" --quiet --preserve')
    out.append(f"matrix ev_cv = ev_pagecol({sn})")
    out += [f'open "@ev_pagedir/{dp}.gdtb" --quiet --preserve', f"series {dn} = ev_freqconv(ev_cv{marg})"]
    if dp != ctx.page:
        out += [f'store "@ev_pagedir/{dp}.gdtb"', f'open "@ev_pagedir/{ctx.page}.gdtb" --quiet --preserve']
    out += [f"list {g} = {' '.join(m)}" for g, m in ctx.groups.items() if ctx.group_page.get(g) == ctx.page]
    out += ["smpl ev_s1 ev_s2", "scalar ev_N = $nobs"]
    return out


def _pagestack(cmd_opts: str, rest: str, ctx: Ctx) -> list[str]:
    """pagestack(page=name) x_? y? -> a panel page with one stacked series per pattern."""
    op = {}
    for k, v in re.findall(r'(\w+)\s*=\s*("[^"]*"|[^,]+)', cmd_opts or ""):
        op[k.lower()] = v.strip().strip('"')
    new = op.get("page") or f"untitled{len(ctx.pages) + 1}"
    left, at, right = rest.partition("@")
    pats = (right if at else left).split()
    if not pats or any("?" not in p for p in pats):
        raise ValueError("pagestack: give pool series with ? for the identifier, e.g. gdp_? cpi_?")
    # a pool object before @ is not needed: identifiers are read from the series names
    pats = [apply_case(p, ctx) for p in pats]
    ctx.need_pages = True
    out = ["smpl full", f'strings ev_sid = ev_stackids("{pats[0]}", dataset)']
    for k, p in enumerate(pats, 1):
        out.append(f'matrix ev_stk{k} = ev_stack("{p}", dataset, ev_sid)')
    out += ["scalar ev_T = rows(ev_stk1)", "scalar ev_NS = nelem(ev_sid)", "matrix ev_idv = seq(1, ev_NS)'",
            "loop ev_j = 1..ev_NS",
            "scalar ev_v = atof(ev_sid[ev_j])",
            "if ok(ev_v)",
            "ev_idv[ev_j] = ev_v",
            "endif",
            "endloop",
            "string ev_pagedir = $dotdir", f'store "@ev_pagedir/{ctx.page}.gdtb"',
            "scalar ev_NT = ev_T * ev_NS", "nulldata ev_NT --preserve",
            "series crossid = vec(ones(ev_T, 1) * ev_idv')",
            "series period = vec(seq(1, ev_T)' * ones(1, ev_NS))"]
    for k, p in enumerate(pats, 1):
        out.append(f"series {p.replace('?', '')} = vec(ev_stk{k})")
    out += ["setobs crossid period --panel-vars", "scalar ev_N = $nobs"]
    ctx.pages.add(new)
    ctx.page = new
    ctx.panel = ("crossid", "period")
    ctx.page_panel[new] = ctx.panel
    return out


# ---------------------------------------------------------------------------
# Program structure: include files and subroutines
# ---------------------------------------------------------------------------

def _join_continuations(text: str, src: str = "") -> list[tuple]:
    raw = text.replace("\r\n", "\n").split("\n")
    lines, buf, start = [], "", 0
    for i, ln in enumerate(raw, 1):         # join continuation lines ending in " _"
        if not buf:
            start = i
        if re.search(r"\s_\s*$", _strip_comment(ln)):
            buf += re.sub(r"\s_\s*$", " ", _strip_comment(ln))
            continue
        lines.append((start if not src else f"{src}:{start}", buf + ln))
        buf = ""
    return lines


def _expand_includes(lines, base_dir, depth=0):
    out = []
    for lineno, ln in lines:
        m = re.fullmatch(r'(?i)\s*include\s+"?([^"\']+?)"?\s*(\'.*)?', ln)
        pargs = []
        if not m:
            m2 = re.fullmatch(r'(?i)\s*(?:run|exec)(?:\([^)]*\))?\s+("[^"]+"|\S+)(.*)', _strip_comment(ln))
            if m2:
                pargs = m2.group(2).split()
                m = m2
            else:
                out.append((lineno, ln))
                continue
        f = m.group(1).strip().strip('"')
        if not re.search(r"\.\w+$", f):
            f += ".prg"
        path = os.path.join(base_dir or ".", *re.split(r"[\\/]", f))
        if depth > 10 or not os.path.exists(path):
            out.append((lineno, f"__include_missing__ {f}"))
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            sub = _join_continuations(fh.read(), os.path.basename(path))
        if pargs:
            # program arguments are text: substitute them into the called program
            def put(line):
                for k in range(len(pargs) - 1, -1, -1):
                    line = line.replace("{%" + str(k) + "}", pargs[k]).replace("%" + str(k), pargs[k])
                return line
            sub = [(n, put(t)) for n, t in sub]
        out.append((lineno, f"' --- include {f}"))
        out += _expand_includes(sub, os.path.dirname(path), depth + 1)
        out.append((lineno, f"' --- end of include {f}"))
    return out


_SUB_RX = re.compile(r"(?i)\s*subroutine\s+(?:local\s+)?(\w+)\s*(?:\((.*)\))?\s*$")


def _collect_subs(lines):
    """Take subroutine ... endsub blocks out of the program: name -> (params, body)."""
    subs, main, cur = {}, [], None
    for lineno, ln in lines:
        code = _strip_comment(ln).strip()
        m = _SUB_RX.fullmatch(code)
        if m and cur is None:
            params = []
            for prm in (m.group(2) or "").split(","):
                toks = prm.split()
                if toks:
                    params.append(toks[-1])          # "series x", "scalar !n", "string %s"
            cur = (m.group(1).lower(), params, [])
            continue
        if cur is not None and re.fullmatch(r"(?i)endsub", code):
            subs[cur[0]] = (cur[1], cur[2])
            cur = None
            continue
        (cur[2] if cur is not None else main).append((lineno, ln))
    return subs, main


def _substitute(line: str, params: list[str], args: list[str]) -> str:
    code, cmt = line, ""
    for prm, arg in zip(params, args):
        if prm[0] in "!%":
            # literal argument "abc" -> abc inside {}, the literal elsewhere;
            # a program variable argument (%t, !i) keeps its braces
            lit = not re.fullmatch(r"[!%]\w+", arg)
            br = arg.strip('"') if lit else "{" + arg + "}"
            code = re.sub(r"\{" + re.escape(prm) + r"\}", lambda _m: br, code)
            code = re.sub(re.escape(prm) + r"(?![A-Za-z0-9_])", lambda _m: arg, code)
        else:
            parts = re.split(r'("[^"]*")', code)
            for i in range(0, len(parts), 2):
                parts[i] = re.sub(r"(?<![A-Za-z0-9_!%@.])" + re.escape(prm) + r"(?![A-Za-z0-9_])",
                                  lambda _m: arg, parts[i], flags=re.IGNORECASE)
            code = "".join(parts)
    return code + cmt


def _expand_calls(lines, subs, depth=0):
    out = []
    for lineno, ln in lines:
        code = _strip_comment(ln).strip()
        m = re.fullmatch(r"(?i)call\s+(\w+)\s*(\(.*\))?", code)
        if not m:
            out.append((lineno, ln))
            continue
        nm = m.group(1).lower()
        if nm not in subs or depth > 20:
            out.append((lineno, f"__call_unknown__ {code}"))
            continue
        params, body = subs[nm]
        args = _call_args(m.group(2), 0)[0] if m.group(2) else []
        args = [a for a in args if a != ""]
        if len(args) != len(params):
            out.append((lineno, f"__call_unknown__ {code}"))
            continue
        out.append((lineno, f"' --- call {m.group(1)}"))
        inner = [(lineno, b if b.strip().startswith("'") else _substitute(b, params, args)) for _, b in body]
        # return: the body runs inside a one-pass loop and return becomes break
        has_ret, lev, marked = False, 0, []
        for ln_, b in inner:
            c = _strip_comment(b).strip().lower()
            w = c.split()[0] if c else ""
            if w in ("for", "while"):
                lev += 1
            elif w in ("next", "wend"):
                lev -= 1
            if c == "return":
                if lev > 0:
                    b = "__return_in_loop__"
                else:
                    b, has_ret = "__return__", True
            marked.append((ln_, b))
        expanded = _expand_calls(marked, subs, depth + 1)
        if has_ret:
            expanded = [(lineno, "__sub_begin__")] + expanded + [(lineno, "__sub_end__")]
        out += expanded
        out.append((lineno, f"' --- end of {m.group(1)}"))
    return out


def translate(text: str, case: str = "keep") -> tuple[str, list[tuple[int, str]]]:
    hansl, todos, _ = translate_full(text, case)
    return hansl, todos


def translate_full(text: str, case: str = "keep", plot_files: bool = False, base_dir: str | None = None,
                   args: list | None = None):
    ctx = Ctx(case=case, plot_files=plot_files)
    lines = _expand_includes(_join_continuations(text), base_dir)
    subs, lines = _collect_subs(lines)
    lines = _expand_calls(lines, subs)

    body, indent, has_wf = [], 0, False
    for lineno, ln in lines:
        stripped = ln.strip()
        if stripped.startswith("'"):
            body.append("    " * indent + "#" + stripped.lstrip("'"))
            continue
        code = _strip_comment(ln)
        try:
            if code.startswith("__include_missing__"):
                code = "include " + code.split(None, 1)[1]
                raise ValueError(f"include file {code.split(None, 1)[1]} not found")
            if code.startswith("__call_unknown__"):
                code = code.split(None, 1)[1]
                raise ValueError("unknown subroutine or wrong number of arguments")
            if code.strip() == "__return_in_loop__":
                code = "return"
                raise ValueError("return inside a loop of a subroutine: restructure with if/else")
            if re.fullmatch(r"(?i)\s*return\s*", code):
                raise ValueError("return outside a subroutine")
            marks = {"__sub_begin__": ["loop 1    # subroutine body (return = break)"],
                     "__sub_end__": ["endloop"], "__return__": ["break"]}
            res = marks.get(code.strip()) or translate_line(code, ctx)
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
    if ctx.args_used or args:
        head.append("# program arguments (EViews %0, %1, ...)")
        for k in range(max(list(ctx.args_used) + [len(args or []) - 1]) + 1):
            v = (args or [])[k] if k < len(args or []) else ""
            head.append(f'string ev_arg{k} = "{v}"')
    return "\n".join(head + [""] + body) + "\n", ctx.todos, ctx.ignored


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("prg", help="EViews program file (.prg)")
    ap.add_argument("-o", "--output", help="output .inp (default: same name)")
    ap.add_argument("--case", choices=["keep", "upper", "lower"], default="keep",
                    help="change series-name case (hansl is case-sensitive)")
    ap.add_argument("--args", nargs="*", default=[],
                    help="program arguments: the values of %%0, %%1, ...")
    ap.add_argument("--plot-files", action="store_true",
                    help="write graphs to plotNN.png instead of showing them (for gretlcli)")
    a = ap.parse_args(argv)
    with open(a.prg, encoding="utf-8", errors="replace") as f:
        text = f.read()
    hansl, todos, ignored = translate_full(text, a.case, a.plot_files, os.path.dirname(os.path.abspath(a.prg)),
                                           a.args)
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
