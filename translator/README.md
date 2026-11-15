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

Forecasts: `eq.forecast(s|d, e, g) yf yf_se` (dynamic by default) and `eq.fit yf` (static).
VARs: `var v.ls 1 2 y1 y2 @ c x` with `.impulse`, `.decomp`, `.testexog`, `.laglen`,
`.makeresids`, `.output`; expressions become helper series built over the whole workfile.
Databases: `store(d=db)`, `fetch(d=db)`, `dbopen`/`db` (gretl `.bin` files).
Pages: `pagecreate(page=x) freq start end`, `pageselect`, `pagedelete`, `pagerename`
(pages are kept as `.gdtb` files in gretl's dot directory; groups are redefined on return).

Not yet: TGARCH/EGARCH, panel pages (`pagestruct`, `pageunstack`), IPS test,
subroutines/`call`, `include`, matrices/vectors, system objects, VEC models.

Use `--plot-files` to write graphs as PNG files when running with gretlcli.

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
