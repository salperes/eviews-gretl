' EViews program: FIML and GMM systems, structural VARs and a model
wfopen "../../data/usmacro.gdt"
series oth = gdp - cons - inv
smpl 1985q1 2019q4

' --- systems
system sf
sf.append dlog(cons) = c(1) + c(2)*dlog(gdp) + c(3)*ffr(-1)
sf.append dlog(gdp) = c(4) + c(5)*dlog(cons) + c(6)*ffr
sf.fiml
system sg
sg.append dlog(cons) = c(1) + c(2)*dlog(gdp)
sg.append inst ffr(-1) dlog(gdp(-1)) dlog(cons(-1))
sg.gmm

' --- structural VAR: A-B pattern and long-run restrictions
var v1.ls 1 2 dlog(cons) dlog(gdp) ffr
matrix(3,3) pa
pa.fill(b=r) 1, 0, 0, na, 1, 0, na, na, 1
matrix(3,3) pb
pb.fill(b=r) na, 0, 0, 0, na, 0, 0, 0, na
v1.svar(rtype=patsr, namea=pa, nameb=pb)
v1.impulse(8)
var v2.ls 1 2 dlog(cons) dlog(gdp)
v2.svar(lr)
v2.decomp(8)

' --- model: consumption and investment equations plus the GDP identity
smpl 1985q1 2015q4
equation eqc.ls dlog(cons) c dlog(cons(-1)) dlog(gdp)
equation eqi.ls dlog(inv) c dlog(inv(-1)) ffr
model m1
m1.merge eqc eqi
m1.append @identity gdp = cons + inv + oth
smpl 2010q1 2019q4
m1.solve
m1.solve(d=s)
