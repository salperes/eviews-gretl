' EViews program: Phase 1 of the gap analysis (docs/GAP_ANALIZI.md)
' TSLS, logit/probit, ARDL with bounds test, equation tests
wfopen "../../data/usmacro.gdt"
smpl 1970q1 2019q4

' E6: two-stage least squares
equation eiv.tsls dlog(cons) c dlog(gdp) @ c ffr(-1) dlog(gdp(-1)) dlog(cons(-1))
eiv.output

' E8: logit and probit of a growth indicator
series up = dlog(gdp) > 0.0075
equation elog.binary(d=l) up c ffr dlog(cons)
equation epro.binary(d=p) up c ffr dlog(cons)
elog.output

' E15: ARDL with automatic lag selection and the bounds test
smpl 1960q1 2019q4
equation eardl.ardl(deplags=4, reglags=4, ic=aic) log(cons) log(gdp)
eardl.output

' T4-T9: tests on a least squares equation
smpl 1970q1 2019q4
equation e1.ls dlog(cons) c dlog(gdp) ffr
e1.hettest(type=bpg)
e1.hettest(type=arch, lags=2)
e1.white
e1.reset(1)
e1.chow 1990q1
e1.chow(f) 2015q1
e1.testadd dlog(cons(-1))
e1.testdrop ffr
e1.rls(c)

' S4, G6, S10: Phillips-Perron, Engle-Granger, moving-average seasonal adjustment
smpl 1960q1 2019q4
series lgdp = log(gdp)
series lcons = log(cons)
lgdp.uroot(pp, trend)
group gc lcons lgdp
gc.coint(method=eg)
gc.coint(method=po)
smpl @all
cons.seas(m) cons_sa cons_sf

' V8-V10: VAR stability, residual tests and forecasts
series dc = dlog(cons)
series dg = dlog(gdp)
smpl 1985q1 2015q4
var v1.ls 1 2 dc dg ffr @ c
v1.arroots
v1.arlm(4)
v1.jbera
smpl 2016q1 2019q4
v1.forecast _f

' W7, W8: an annual page with series converted from the quarterly page
pagecreate(page=annual) a 1990 2019
copy(c=a) usmacro\gdp gdp_avg
copy(c=s) usmacro\gdp gdp_sum
show gdp_avg gdp_sum
pageselect usmacro
copy gdp gdp_copy

' F4-F8: distributions, strings, logical helpers
scalar pv = 1 - @ctdist(1.96, 1000)
%name = "gdp"
%label = @upper(%name) + "_" + @str(2020)
series pos = @recode(dlog(gdp) > 0, 1, 0)
show pv

' O3, P8: a table object and exitloop
table(3,2) tab
tab(1,1) = "Variable"
tab(1,2) = "Mean"
tab(2,1) = %label
tab(2,2) = @mean(gdp)
tab.setwidth(a) 14
tab.save(t=csv) phase1_table
show tab
!n = 0
for !i = 1 to 10
  if !i > 3 then
    exitloop
  endif
  !n = !n + 1
next
show !n

' S10: Census X-13 seasonal adjustment (needs the x13as program set up in gretl)
pageselect usmacro
smpl 1960q1 2019q4
cons.x13(save="d10 d11")
show cons_d11
