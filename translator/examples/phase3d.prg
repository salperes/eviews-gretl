' EViews program: the last P2 items of the gap analysis (docs/GAP_ANALIZI.md)
wfopen "../../data/usmacro.gdt"
smpl 1960q1 2019q4
series lgd = log(gdp)
series oth = gdp - cons - inv

' W14: alpha series from expressions
alpha decade = @left(@str(@year), 3) + "0s"
alpha regime = "low"
smpl if ffr > 5
alpha regime = "high"
smpl 1960q1 2019q4
alpha tag = @upper(regime) + "-" + decade
series taglen = @len(tag)
series ishigh = (regime = "high")

' S6: breakpoint unit root tests (innovational and additive outlier models)
lgd.buroot(trend=trendconst, break=const)
lgd.buroot(break=trendconst, breaktype=outlier, method=maxabsint, lagmethod=aic)
ffr.buroot(trend=const, date=1980q1, lag=2)

' O4: graph formatting
group gl lgd
freeze(gp) gl.line
gp.addtext(t) "Log real GDP"
gp.draw(shade, bottom, 2007q4, 2009q2)
gp.draw(dashline, bottom, 1980q1, red)
gp.draw(line, left, 9.5)
gp.axis(left) zeroline grid
gp.axis(bottom) angle(45)
gp.datelabel interval(year, 10)
gp.legend columns(1) inbox
gp.setelem(1) lcolor(blue) lwidth(2)
gp.save(t=png) phase3d_lines
group gf ffr
freeze(gr) gf.line
gr.options size(8,3) -frame
gr.setelem(1) symbol(filledcircle)
graph gm.merge gp gr
gm.save(t=png) phase3d_merged

' O5: pie graph of the GDP components
group comp cons inv oth
smpl 2019q1 2019q4
freeze(pie1) comp.pie
pie1.save(t=png) phase3d_pie
