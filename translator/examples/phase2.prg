' EViews program: Phase 2 of the gap analysis (docs/GAP_ANALIZI.md)
wfopen "../../data/usmacro.gdt"
smpl 1970q1 2019q4
series dg = dlog(gdp)
series dc = dlog(cons)

' E9-E13: ordered, censored, count and quantile regressions
series cat = 1 + (dg > 0.004) + (dg > 0.009)
equation eord.ordered(d=l) cat ffr dc
series yt = @recode(dg > 0, 100*dg, 0)
equation etob.censored(l=0) yt c ffr
series cnt = @round(ffr)
equation epoi.count(d=p) cnt c dg
equation eq25.qreg(quant=0.25) dc c dg

' E22, E7: weighted least squares, LIML and single-equation GMM
series wser = 1 + abs(ffr)
equation ewls.ls(w=wser) dc c dg
equation eliml.liml dc c dg @ c ffr(-1) dg(-1) dc(-1)
equation egmm.gmm dc c dg @ c ffr(-1) dg(-1) dc(-1)

' E3: GARCH with Student's t errors
series r = 100*dg
equation egt.arch(1,1,tdist) r c

' E16: cointegrating regressions
smpl 1960q1 2019q4
series lc = log(cons)
series lgd = log(gdp)
equation efm.cointreg lc lgd
equation edo.cointreg(method=dols, lead=2, lag=2) lc lgd

' T5, T10, T12: residual correlogram, Quandt-Andrews, VIF
smpl 1970q1 2019q4
equation e1.ls dc c dg ffr
e1.correlogram(8)
e1.ubreak(15)
e1.varinf
' G5: pairwise Granger causality
group gg dc dg
gg.cause(2)
' V6-V8, Y6: VAR White test, impulse responses with bootstrap bands, VAR as a model, restricted VEC
smpl 1985q1 2015q4
var v1.ls 1 2 dc dg ffr @ c
v1.white
v1.impulse(8, imp=gen, se=boot, rep=50)
v1.makemodel(mv)
smpl 2016q1 2019q4
mv.solve
smpl 1960q1 2019q4
var vec1.ec(c, 1) 1 2 lc lgd

' S5-S16, G7: more unit root tests, filters, smoothing, interpolation, plots, principal components
smpl 1960q1 2019q4
lgd.uroot(dfgls)
lgd.uroot(np)
lgd.buroot(break=intercept)
lgd.bpf(type=cf) lgd_cyc
smpl 1970q1 2019q4
dg.smooth(s) dg_sm
dg.qqplot
group gpc dc dg
gpc.pcomp pc1
