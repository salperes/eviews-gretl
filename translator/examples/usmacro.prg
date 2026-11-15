' EViews program: US consumption and investment (FRED data)
wfopen "../../data/usmacro.gdt"

' growth rates and inflation
series dlc = dlog(CONS)
series dly = dlog(GDP)
genr infl = @pcy(CPI)
series ffr_ma = @movav(FFR, 4)
scalar g_mean = @mean(dly)

smpl 1985q1 2019q4
equation eq_cons.ls dlog(CONS) c dlog(GDP) dlog(CONS(-1)) FFR
eq_cons.wald c(2)=0.5, c(4)=0
eq_cons.auto(4)
freeze(tab_cons) eq_cons

' investment with HAC standard errors, trend and seasonals
equation eq_inv.ls(cov=hac) log(INV) c log(GDP) FFR @trend _
   @seas(1) @seas(2) @seas(3)
eq_inv.wald c(5)=0, c(6)=0, c(7)=0

' rolling start dates
for !y = 1985 to 1995 step 5
   smpl {!y}q1 2019q4
next
for !k = 1 to 3
   series lag_ffr{!k} = FFR(-!k)
next

!big = 0
if g_mean > 0.005 and !big = 0 then
   !big = 1
else
   !big = 2
endif

smpl @all
ls(h) dlog(INV) c dlog(GDP)
eq_cons.makeresids res_cons
wfsave usmacro_out.wf1
