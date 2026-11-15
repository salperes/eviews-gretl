' EViews program: logl and sspace objects (gap items O7, O6)
wfopen "../../data/usmacro.gdt"
smpl 1970q1 2019q4
series dc = dlog(cons)
series dg = dlog(gdp)
' custom likelihood: linear regression with normal errors
param c(1) 0 c(2) 0 c(3) 0.01
logl ll1
ll1.append @logl lc
ll1.append res = dc - c(1) - c(2)*dg
ll1.append lc = log(@dnorm(res/c(3))) - log(c(3))
ll1.ml
' state space: local level model for log GDP
series ly = log(gdp)
sspace ss1
ss1.append @signal ly = lev + [var = exp(c(1))]
ss1.append @state lev = lev(-1) + [var = exp(c(2))]
ss1.append @param c(1) -9 c(2) -9
ss1.ml
' a formatted graph saved to a file
graph gr1.line dc dg
gr1.addtext(t) "Consumption and GDP growth"
gr1.setelem(1) lcolor(blue) lwidth(2)
gr1.save(t=png) ml_objects_graph
