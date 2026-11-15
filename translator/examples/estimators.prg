' EViews program: explicit equations, ARMA, systems and VEC models
wfopen "../../data/usmacro.gdt"
smpl 1985q1 2015q4
equation eq_nls.ls cons = c(1)*gdp^c(2)
equation eq_arma.ls dlog(gdp) c dlog(cons) ar(1) ma(1)
equation eq_g.ls dlog(cons) c dlog(cons(-1)) dlog(gdp)
smpl 2016q1 2019q4
eq_g.forecast(e) cons_f cons_se
eq_g.forecast(d) dcons_f
eq_arma.forecast gdp_f

smpl 1985q1 2019q4
system sys1
sys1.append dlog(cons) = c(1) + c(2)*dlog(gdp)
sys1.append dlog(inv) = c(3) + c(2)*dlog(gdp) + c(4)*ffr
sys1.append inst ffr(-1) dlog(gdp(-1)) dlog(cons(-1)) ffr
sys1.3sls
sys1.wald c(2)=1

smpl 1960q1 2019q4
series lc = log(cons)
series lg = log(gdp)
group g lc lg
g.coint(c, 2)
var v1.ec(c, 1) 1 2 lc lg
v1.impulse(8)
