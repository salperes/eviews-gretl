' EViews program: Phase 3 (C) of the gap analysis (docs/GAP_ANALIZI.md)
wfopen "../../data/usmacro.gdt"
smpl 1960q1 2019q4
series lc = log(cons)
series lgd = log(gdp)
series li = log(inv)
series dc = dlog(cons)
series dg = dlog(gdp)

' V6: VEC with restrictions on the cointegrating vector and the adjustment
var ve.ec(c, 1) 1 2 lc lgd
ve.append(coint) B(1,1)=1, B(1,2)=-1
var ve2.ec(c, 1) 1 2 lc lgd
ve2.append(coint) B(1,1)=1, A(1,1)=0

' V12: Bayesian VAR, Litterman prior
smpl 1970q1 2019q4
var vb.bvar(prior=lit, l1=0.1, l2=0.99) 1 2 dc dg @ c

' O10: factor analysis
factor f1.ml(n=1) dc dg li

' O9: spool of output
spool sp
sp.append vb f1
sp.save sp_out

' O4, O5: graph legend names, grid, seasonal graph
group gl lc lgd
freeze(gp) gl.line
gp.name(1) "log consumption"
gp.options grid
gp.save(t=png) phase3c_lines
dc.seasplot

' O6: state space with a constant in the state equation (random walk with drift)
sspace ss1
ss1.append @signal lgd = sv1
ss1.append @state sv1 = c(1) + sv1(-1) + [var = exp(c(2))]
ss1.append @param c(1) 0.008 c(2) -9
ss1.ml
ss1.makestates(t=smooth) *_sm

' Y7: model control: the FFR path that makes consumption growth hit a target
smpl 1980q1 2019q4
equation eqd.ls dc c dc(-1) ffr
model mc
mc.merge eqd
series dc_target = 0.0071
smpl 2015q1 2019q4
mc.control ffr dc dc_target

' O8: pool regression with fixed cross-section effects
smpl 1970q1 2019q4
series y_us = dc
series y_uk = dg
series x_us = dg(-1)
series x_uk = dc(-1)
pool p1 _us _uk
p1.ls(cx=f) y? c x?
