' EViews program exercising forecasts, VARs, databases and workfile pages
wfopen "../../data/usmacro.gdt"

' --- forecast: estimate to 2015, forecast 2016-2019
smpl 1985q1 2015q4
equation eq_ffr.ls ffr c ffr(-1) dlog(gdp)
smpl 2016q1 2019q4
eq_ffr.forecast(e) ffr_dyn ffr_se
eq_ffr.fit ffr_stat

' --- VAR with lags 1-2
smpl 1985q1 2019q4
var v1.ls 1 2 dlog(cons) dlog(gdp) ffr @ c
v1.testexog
v1.decomp(8)
v1.impulse(10)
v1.makeresids r_cons r_gdp r_ffr

' --- database: store two series, fetch one back under a new page
store(d=macro) gdp ffr
pagecreate(page=annual) a 1990 2019
fetch(d=macro) gdp
show gdp
pageselect usmacro
smpl @all
scalar n_q = @obssmpl
