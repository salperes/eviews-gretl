' EViews program: TARCH, EGARCH and ARCH-M, subroutines and include,
' matrix algebra, panel pages, IPS test, panel estimators, pageunstack and pagestack
include "lib_matrix"
wfopen "../../data/usmacro.gdt"
series r = 100*dlog(gdp)
smpl 1960q1 2019q4

' ARCH family: arch(ARCH order, GARCH order[, t | e])
equation eg.arch(1,1) r c
equation et.arch(1,1,t) r c
et.makegarch ht
series ut = resid
' one-step variance forecast from the TARCH coefficients (as in EViews)
series hf = @coefs(2) + @coefs(3)*ut^2 + @coefs(4)*ut^2*(ut<0) + @coefs(5)*ht
equation ee.arch(1,1,e) r c
ee.makegarch he
' GARCH-in-mean and a TARCH(2,1) with one threshold term
equation em.arch(1,1,archm=sd) r c
equation et2.arch(2,1,thrsh=1) r c

' matrix algebra in a subroutine from the include file
call olsmat(cons, gdp)
equation eqc.ls cons c gdp
scalar gap = @abs(bm(2,1) - @coefs(2))
call report("gap", gap)
matrix(2,2) a
a.fill 2, 1, 1, 3
matrix ai = @inverse(a)
scalar check = @det(a) * @trace(ai)
matrix k = @kronecker(@identity(2), a)
vector ev = @eigenvalues(a)
matrix c2 = @columnextract(k, 2)
smpl 2019q1 2019q4
mtos(c2, c2s)   ' the vector fills the 4 observations of the sample
smpl 1960q1 2019q4
call report("check", check)

' panel page: unit root tests and unstacking
wfopen "../../data/panel_demo.csv"
pagestruct id @date(year)
ly.uroot(ips, maxlag=2)
' panel least squares: two-way fixed effects and random effects
equation epf.ls(cx=f, per=f) ly c ly(-1)
equation epr.ls(cx=r) ly c ly(-1)
pageunstack(namepat="*_?", page="wide") id year @ ly
show ly_11 ly_13

' stack the wide page back into a panel page
pagestack(page=long) ly_?
equation efe.ls(cx=f) ly_ c ly_(-1)
efe.makeresid ufe
show ufe
