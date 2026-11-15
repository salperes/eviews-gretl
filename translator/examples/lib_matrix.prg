' Subroutines used by garch_panel.prg (pulled in with include)
subroutine olsmat(series y, series x)
  ' least squares by matrix algebra: b = (X'X)^-1 X'y
  series one = 1
  group gx one x
  stom(y, yv)
  stom(gx, xm)
  matrix xx = @transpose(xm)*xm
  matrix bm = @inverse(xx)*@transpose(xm)*yv
  scalar nr = @rows(xm)
endsub

subroutine report(string %what, scalar !value)
  ' nothing to report for a missing value
  if !value = na then
    return
  endif
  scalar {%what}_val = !value
  show {%what}_val
endsub
