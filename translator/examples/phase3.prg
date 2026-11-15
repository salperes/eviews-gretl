' EViews program: Phase 3 of the gap analysis (docs/GAP_ANALIZI.md)
wfopen "../../data/usmacro.gdt"
smpl 1960q1 2019q4
series dc = dlog(cons)
series dg = dlog(gdp)
series r = 100*dg

' E3: power ARCH and component GARCH
equation ep.arch(1,1,parch) r c
equation ecg.arch(1,1,cgarch) r c

' E14, E19, E17: robust and stepwise LS, GLM, breaks, thresholds, Markov switching
smpl 1970q1 2019q4
equation erob.robustls dc c dg
equation estep.stepls dc c @ dg ffr dg(-1) dc(-1)
equation eglm.glm(family=normal) dc c dg
equation ebrk.breakls(maxbreaks=3) dc c
equation eth.threshold dc c dc(-1) @ dc(-1)
equation esw.switchreg dg c

' E16: canonical cointegrating regression
smpl 1960q1 2019q4
series lc = log(cons)
series lgd = log(gdp)
equation eccr.cointreg(method=ccr) lc lgd

' E20: lasso with cross-validated penalty
smpl 1970q1 2019q4
equation elas.enet(penalty=lasso) dc c dg ffr dg(-1) dc(-1)
