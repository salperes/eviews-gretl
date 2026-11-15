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
