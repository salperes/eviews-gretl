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
