# evprg2hansl: EViews program (.prg) → gretl script (.inp)

```bash
/opt/homebrew/bin/python3 evprg2hansl.py program.prg
```

Writes `program.inp` next to the `.prg`. Lines it cannot translate are kept as
`# TODO(EViews line N, ...)` comments and listed on screen. Uses only the Python
standard library; the output needs the EViewsCompat gretl package installed.

hansl is case-sensitive and EViews is not: if your program writes `gdp` but the
data has `GDP`, add `--case upper` (or `--case lower`).

## Supported
| EViews | gretl |
|---|---|
| `wfopen`, `wfcreate a/q/m/u`, `wfsave` | `open`, `nulldata` + `setobs`, `store` (.wf1 → .gdt) |
| `smpl 1985q1 2019q4`, `@all`, `@first`, `@last`, `if ...`, `{!y}q1` | `smpl` (+ `--restrict`, `obsnum`) |
| `series`, `genr`, `scalar`, `!x =`, `%s =`, `group` | `series`, `scalar`, `string`, `list` |
| `dlog d log exp abs sqr`, `@pch @pcy @movav @mean @trend @seas` … | hansl / EViewsCompat functions |
| `equation e.ls(cov=white\|hac\|h\|n) ...`, bare `ls` | `ev_ls(...)` |
| `e.wald`, `e.auto(k)`, `e.white`, `e.hettest`, `freeze(t) e` | `ev_wald`, `ev_diag`, `ev_freeze` |
| `for !i = a to b [step s]` / `next`, `for %s ...`, `if/else/endif`, `while/wend` | `loop` / `endloop`, `if` |
| `' comments`, ` _` line continuation | `#`, joined lines |

Also: `eq.fit` / `eq.makeresid` / `resid`, `@coefs(k)`, `equation e.arch(p,q)` (GARCH),
`x.hpf`, `x.uroot(adf|kpss|llc)`, graphs (`g.line`, `graph g.line`, `.bar`, `.scat`;
styling lines are ignored), `sort`, daily workfiles and dates, `@first+!i` sample
arithmetic, `{%x}` / `x_!i` program variables, group elements `g(!i)`.

Forecasts: `eq.forecast(e, g, d) yf yf_se` (dynamic) and `eq.fit yf` (static); like EViews,
a dlog(Y)/d(Y)/log(Y) equation forecasts Y unless option `d` asks for the expression.
Explicit equations `y = c(1) + c(2)*x` and ARMA terms `ar(k)`/`ma(k)` go to `ev_ls`.
VARs: `var v.ls 1 2 y1 y2 @ c x` with `.impulse`, `.decomp`, `.testexog`, `.laglen`,
`.makeresids`, `.output`, `.coint`; VEC: `var v.ec(case, rank) 1 2 y1 y2`.
Systems: `system s1`, `s1.append y = c(1) + c(2)*x`, `s1.append inst z1 z2`,
`s1.ls|wls|sur|tsls|wtsls|3sls|gmm|fiml`, `.wald`, `.makeresids` (FIML runs gretl's own
system estimator at the top level of the script).
Matrices: `matrix(r,c) a`, `a.fill(b=r) 1, 0, na, ...`, `a(i,j) = v`.
Structural VAR: `v.svar(rtype=patsr, namea=a, nameb=b)` and `v.svar(lr)`.
Models: `model m`, `m.merge eq1 eq2`, `m.append @identity y = ...`, `m.solve` / `m.solve(d=s)`
(solutions in `<name>_0` series). Johansen test: `group.coint(case, lags)`.
Databases: `store(d=db)`, `fetch(d=db)`, `dbopen`/`db` (gretl `.bin` files).
Pages: `pagecreate(page=x) freq start end`, `pageselect`, `pagedelete`, `pagerename`.
`d()` and `dlog()` of a series or of its lag are written with explicit lags, so the first
observation of a sample uses earlier data, as in EViews.

Not yet: TGARCH/EGARCH, panel pages (`pagestruct`, `pageunstack`), IPS test,
subroutines/`call`, `include`, matrix algebra beyond declare/fill/element assignment,
model scenarios and stochastic simulation, text-form SVAR restrictions.

## Real programs (`real_prg/`, local testing only: the source repos have no licence)
| Program | Lines | Untranslated | Ran in gretl |
|---|---|---|---|
| intro.prg (course intro) | 28 | 0 | yes (synthetic data) |
| outputgap.prg (HP filter, Okun) | 35 | 0 | yes (US FRED data) |
| randomwalk.prg (spurious regression) | 31 | 0 | yes |
| rolling.prg (rolling GARCH VaR) | 43 | 0 | yes (synthetic data) |
| preston_rolling.prg | 65 | 5 (TGARCH/EGARCH) | not run |
| uroots.prg (panel unit roots) | 38 | 3 (panel pages, IPS) | not run |

## Tests
```bash
/opt/homebrew/bin/python3 -m unittest test_evprg2hansl
```
`examples/usmacro.prg` is a sample program on the FRED dataset (`../data/usmacro.gdt`).
