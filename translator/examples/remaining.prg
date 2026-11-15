' EViews program: nonlinear and HAC-GMM systems, text SVAR restrictions,
' model scenarios, add factors and stochastic simulation
wfopen "../../data/usmacro.gdt"
series oth = gdp - cons - inv
smpl 1985q1 2015q4

system snl
snl.append cons = c(1)*gdp^c(2)
snl.append inv = c(3)*gdp^c(2)
snl.sur
system sh
sh.append dlog(cons) = c(1) + c(2)*dlog(gdp)
sh.append inst ffr(-1) dlog(gdp(-1)) dlog(cons(-1))
sh.gmm(w=hac)

var v1.ls 1 2 dlog(cons) dlog(gdp) ffr
text tr
tr.append @e1 = c(1)*@u1
tr.append @e2 = c(2)*@e1 + c(3)*@u2
tr.append @e3 = c(4)*@e1 + c(5)*@e2 + c(6)*@u3
v1.svar(rtype=text) tr
var v2.ls 1 2 dlog(gdp) dlog(cons)
text lr
lr.append @lr2(@u1) = 0
v2.svar(rtype=lrtext) lr
v2.impulse(8)

equation eqc.ls dlog(cons) c dlog(cons(-1)) dlog(gdp)
equation eqi.ls dlog(inv) c dlog(inv(-1)) ffr
model m1
m1.merge eqc eqi
m1.append @identity gdp = cons + inv + oth
smpl 2010q1 2019q4
m1.addinit(v=n) @all
m1.solve(d=s)
series oth_1 = oth + 100
m1.scenario "Scenario 1"
m1.override oth
m1.solve
m1.scenario "Baseline"
m1.solve(s=s, r=30)
