import unittest

from evprg2hansl import Ctx, Ignored, translate, translate_date, translate_expr, translate_line


def tl(line, **kw):
    return translate_line(line, Ctx(**kw))


class Expr(unittest.TestCase):
    def test_functions(self):
        c = Ctx()
        self.assertEqual(translate_expr("dlog(y) + d(x) + LOG(z)", c), "ldiff(y) + diff(x) + log(z)")
        self.assertEqual(translate_expr("@pch(x)*100", c), "ev_pch(x)*100")
        self.assertEqual(translate_expr("@trend + @seas(2)", c), "ev_trend() + ev_seas(2)")
        self.assertEqual(translate_expr("@movav(FFR, 4)", c), "ev_movav(FFR, 4)")

    def test_names_containing_d_are_kept(self):
        self.assertEqual(translate_expr("gd(-1) + dd", Ctx()), "gd(-1) + dd")

    def test_program_vars(self):
        c = Ctx()
        self.assertEqual(translate_expr("x{!i} + !k", c), "x$i + k")
        self.assertEqual(translate_expr("{%s}_1", c), "@s_1")

    def test_condition(self):
        c = Ctx()
        self.assertEqual(translate_expr("a = 1 and b <> 2", c, condition=True), "a == 1 && b != 2")
        self.assertEqual(translate_expr("a >= 1 or not b", c, condition=True), "a >= 1 || ! b")
        self.assertEqual(translate_expr("!v = na or x <> na", c, condition=True), "missing(v) || !missing(x)")

    def test_string_literal_untouched(self):
        self.assertEqual(translate_expr('"d(x) and y"', Ctx()), '"d(x) and y"')

    def test_case(self):
        self.assertEqual(translate_expr("dlog(cons) + gdp", Ctx(case="upper")), "ldiff(CONS) + GDP")


class Dates(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(translate_date("1985q1"), "1985:1")
        self.assertEqual(translate_date("1990M3"), "1990:03")
        self.assertEqual(translate_date("1990"), "1990")


class Statements(unittest.TestCase):
    def test_smpl(self):
        self.assertEqual(tl("smpl 1985q1 2019q4"), ["smpl full", "smpl 1985:1 2019:4"])
        self.assertEqual(tl("smpl @all"), ["smpl full"])
        self.assertEqual(tl("smpl @first 2000q4"), ["smpl full", "smpl 1 2000:4"])
        self.assertEqual(tl("smpl 1990q1 2000q4 if x > 0"),
                         ["smpl full", "smpl 1990:1 2000:4", "smpl x > 0 --restrict"])
        self.assertEqual(tl("smpl 1/4/2012 1/31/2018"), ["smpl full", "smpl 2012-01-04 2018-01-31"])

    def test_smpl_arithmetic(self):
        c = Ctx()
        self.assertEqual(translate_line("smpl @first+1 @last", c),
                         ["smpl full", "scalar ev_t1 = 1+1", "smpl ev_t1 ev_N"])
        self.assertTrue(c.need_N)

    def test_smpl_program_var(self):
        self.assertEqual(tl("smpl {!y}q1 2019q4"),
                         ["smpl full", 'scalar ev_t1 = obsnum(sprintf("%d:1", y))', "smpl ev_t1 2019:4"])

    def test_for_step(self):
        self.assertEqual(tl("for !y = 1985 to 1995 step 5"), ["loop for (y=1985; y<=1995; y+=5)"])
        self.assertEqual(tl("for !y = 10 to 1 step -1"), ["loop for (y=10; y>=1; y+=-1)"])

    def test_wfcreate(self):
        N = "scalar ev_N = $nobs"
        self.assertEqual(tl("wfcreate q 1990 2000"), ["nulldata 44", "setobs 4 1990:1 --time-series", N])
        self.assertEqual(tl("wfcreate m 2000m3 2000m12"), ["nulldata 10", "setobs 12 2000:03 --time-series", N])
        self.assertEqual(tl("wfcreate u 100"), ["nulldata 100", N])
        self.assertEqual(tl("wfcreate(wf=x,page=y) y 1980 2011"), ["nulldata 32", "setobs 1 1980 --time-series", N])
        # 2000-01-01 is a Saturday: first weekday is 2000-01-03
        self.assertEqual(tl("wfcreate d5 1/1/2000 1/14/2000"), ["nulldata 10", "setobs 5 2000-01-03 --time-series", N])

    def test_equation(self):
        self.assertEqual(tl("equation eq1.ls y c x(-1)"), ['bundle eq1 = ev_ls("y c x(-1)", dataset)'])
        self.assertEqual(tl("equation eq1.ls(cov=white) y c x"),
                         ['bundle eq1 = ev_ls("y c x", dataset, "white")'])
        self.assertEqual(tl("eq2.ls(n) y c x"), ['bundle eq2 = ev_ls("y c x", dataset, "hac")'])
        self.assertEqual(tl("ls y c x"), ['bundle eq_untitled1 = ev_ls("y c x", dataset)'])

    def test_methods(self):
        self.assertEqual(tl("eq1.wald c(2)=0, c(3)=0"), ['bundle eq1_wald = ev_wald(eq1, "c(2)=0, c(3)=0")'])
        self.assertEqual(tl("eq1.auto(4)"), ["bundle eq1_diag = ev_diag(eq1, 4)"])
        self.assertEqual(tl("freeze(t1) eq1"), ['ev_freeze(eq1, "t1.txt")'])
        self.assertEqual(tl("freeze(t1) eq1.output"), ['ev_freeze(eq1, "t1.txt")'])

    def test_assignments(self):
        self.assertEqual(tl("series y = dlog(x)"), ["series y = ldiff(x)"])
        self.assertEqual(tl("!a = 3"), ["scalar a = 3"])
        self.assertEqual(tl('%s = "GDP"'), ['string s = "GDP"'])
        self.assertEqual(tl("z = x + 1"), ["series z = x + 1"])
        self.assertEqual(tl("group g x y z"), ["list g = x y z"])

    def test_unsupported(self):
        with self.assertRaises(ValueError):
            tl("sys1.fiml")


class RealPrograms(unittest.TestCase):
    """Constructs met in real EViews course programs."""

    def test_index_var_glued_to_name(self):
        c = Ctx()
        translate_line("for !a = 1 to 15", c)
        self.assertEqual(translate_line("series r_!a = r_!a(-1) + 1+(-2)*rnd", c),
                         ["series r_$a = r_$a(-1) + 1+(-2)*uniform()"])

    def test_foreach_string_var(self):
        c = Ctx()
        self.assertEqual(translate_line('%list = "t10 vix"', c), ['string s_list = "t10 vix"'])
        self.assertEqual(translate_line("for %x {%list}", c), ["loop foreach x @s_list"])
        self.assertEqual(translate_line("series dl{%x} = dlog({%x})", c), ["series dl$x = ldiff($x)"])

    def test_fit_resid(self):
        c = Ctx()
        translate_line("equation eq1.ls f10 c t10", c)
        self.assertEqual(translate_line("eq1.fit f10_fit", c),
                         ["bundle eq1_fc = ev_forecast(eq1, dataset, 0, 1, 1)", "series f10_fit = ev_fcast_series(eq1_fc, eq1_fc.level)"])
        self.assertEqual(translate_line("eq1.makeresid r1", c), ["series r1 = ev_resid(eq1)"])
        self.assertEqual(translate_line("genr u = resid", c), ["series u = ev_resid(eq1)"])
        with self.assertRaises(Ignored):
            translate_line("show eq1", c)

    def test_hpf(self):
        self.assertEqual(tl("ly.hpf(lambda=6.25) lytrend @ lycycle"),
                         ["series lytrend = ly - hpfilt(ly, 6.25)", "series lycycle = hpfilt(ly, 6.25)"])

    def test_graphs(self):
        c = Ctx()
        translate_line("group g1 f10 t10", c)
        self.assertEqual(translate_line("g1.line", c), ["gnuplot g1 --time-series --with-lines --output=display"])
        self.assertEqual(translate_line("graph p.line y ytrend", c),
                         ["gnuplot y ytrend --time-series --with-lines --output=display"])
        with self.assertRaises(Ignored):
            translate_line('p.addtext(t) "Title"', c)
        translate_line("group g2 dly du", c)
        self.assertEqual(translate_line("freeze(gr) g2.scat", c), ["gnuplot du dly --output=display"])

    def test_uroot(self):
        self.assertEqual(tl("x.uroot(adf,info=aic,maxlag=10)"), ["adf 10 x --c --test-down=AIC"])
        self.assertEqual(tl("freeze(u1) x.uroot(adf,trend,maxlag=4)"),
                         ['outfile "u1.txt" --quiet', "    adf 4 x --ct", "end outfile"])

    def test_garch(self):
        c = Ctx()
        out = translate_line("equation eq1.arch(1,1) yy c", c)
        self.assertEqual(out[0], "catch garch 1 1 ; yy const --quiet")
        self.assertEqual(translate_line("eq1.makegarch h", c), ["series h = eq1_h"])
        self.assertEqual(translate_line("hf = @coefs(2)+@coefs(3)*resid(-1)^2", c),
                         ["series hf = eq1.coeff[2]+eq1.coeff[3]*eq1_resid(-1)^2"])
        # EViews arch(ARCH, GARCH) -> gretl garch GARCH ARCH
        self.assertEqual(translate_line("equation e9.arch(1,2) yy c", c)[0], "catch garch 2 1 ; yy const --quiet")
        self.assertEqual(translate_line("equation eq2.arch(1,1,t) yy c", c)[0],
                         'bundle ev_gb = ev_garch("yy c", dataset, "tarch", 1, 1, 1)')
        out = translate_line("equation eq3.arch(1,1,e) yy c", c)
        self.assertEqual(out[0], 'bundle ev_gb = ev_garch("yy c", dataset, "egarch", 1, 1, 1)')
        self.assertIn("bundle eq3 = ev_gb", out)
        self.assertEqual(translate_line("eq3.makegarch h", c), ["series h = eq3_h"])
        self.assertEqual(translate_line("u = resid", c), ["series u = eq3_resid"])
        self.assertEqual(translate_line("eq3.output", c), ["ev_garchprint(&eq3)"])
        self.assertEqual(translate_line("equation eq4.arch(1,1,archm=sd) yy c", c)[0],
                         'bundle ev_gb = ev_garch("yy c", dataset, "garch", 1, 1, 1, "sd")')
        self.assertEqual(translate_line("equation eq5.arch(2,1,thrsh=1) yy c", c)[0],
                         'bundle ev_gb = ev_garch("yy c", dataset, "garch", 2, 1, 1, null, 1)')
        with self.assertRaises(ValueError):
            translate_line("equation eq6.arch(1,1,archm=foo) yy c", c)

    def test_panel_ls(self):
        c = Ctx()
        translate_line("pagestruct id @date(t)", c)
        self.assertEqual(translate_line("equation ef.ls(cx=f) y c x(-1)", c),
                         ['bundle ef = ev_panel("y c x(-1)", dataset, "fixed", 0)'])
        self.assertEqual(translate_line("equation er.ls(cx=r, per=f) y c x", c),
                         ['bundle er = ev_panel("y c x", dataset, "random", 1)'])
        self.assertEqual(translate_line("equation ep.ls y c x", c),
                         ['bundle ep = ev_panel("y c x", dataset, "none", 0)'])
        self.assertEqual(translate_line("ef.makeresid u", c), ["series u = ev_resid(ef)"])
        self.assertEqual(translate_line("ef.output", c), ["ev_panelprint(&ef)"])

    def test_pagestack(self):
        c = Ctx()
        out = translate_line("pagestack(page=long) gdp_? cpi?", c)
        self.assertIn('strings ev_sid = ev_stackids("gdp_?", dataset)', out)
        self.assertIn("series gdp_ = vec(ev_s1)", out)
        self.assertIn("series cpi = vec(ev_s2)", out)
        self.assertIn("setobs crossid period --panel-vars", out)
        self.assertEqual(c.page, "long")
        self.assertEqual(c.panel, ("crossid", "period"))
        with self.assertRaises(ValueError):
            translate_line("pagestack gdp", Ctx())

    def test_panel(self):
        c = Ctx()
        self.assertEqual(translate_line("pagestruct panelid @date(date)", c)[0], "setobs panelid date --panel-vars")
        self.assertEqual(translate_line("x.uroot(ips,info=aic,maxlag=10)", c), ["adf 10 x --c --test-down=AIC"])
        self.assertEqual(translate_line("x.uroot(llc,maxlag=4)", c),
                         ["if $datatype == 3", "levinlin 4 x", "else", "adf 4 x --c", "endif"])
        out = translate_line('pageunstack(namepat="*_?",page="un") panelid date @ x', c)
        self.assertIn("matrix ev_u1 = ev_unstack(x)", out)
        self.assertIn('string ev_nm = sprintf("x_%g", ev_uid[ev_j])', out)
        self.assertEqual(c.page, "un")
        with self.assertRaises(ValueError):
            translate_line("pageunstack id t @ x", Ctx())

    def test_matrix_algebra(self):
        c = Ctx()
        self.assertEqual(tl("vector(3) v"), ["matrix v = zeros(3, 1)"])
        self.assertEqual(tl("rowvector(4) r = 2"), ["matrix r = ones(1, 4) * 2"])
        self.assertEqual(translate_line("matrix(2,2) m", c), ["matrix m = zeros(2, 2)"])
        self.assertEqual(translate_line("matrix b = @inverse(@transpose(x)*x)", c), ["matrix b = inv(transp(x)*x)"])
        self.assertEqual(translate_line("matrix k = @kronecker(@identity(2), m)", c), ["matrix k = (I(2) ** m)"])
        self.assertEqual(translate_line("scalar d = @det(m) + m(1,2) * @trace(m)", c), ["scalar d = det(m) + m[1,2] * tr(m)"])
        self.assertEqual(translate_line("m = @emult(m, m)", c), ["matrix m = (m .* m)"])
        self.assertEqual(translate_line("matrix e = @subextract(m,1,2,2,2)", c), ["matrix e = m[1:2,2:2]"])
        self.assertEqual(translate_line("matrix c2 = @columnextract(m,2)", c), ["matrix c2 = m[,2]"])
        self.assertEqual(translate_line("stom(y, ym)", c), ["matrix ym = {y}"])
        self.assertEqual(translate_line("mtos(ym, y2)", c), ["series y2 = ym"])
        self.assertEqual(translate_line("m(1,1) = 5", c), ["m[1,1] = 5"])


class Phase1Equations(unittest.TestCase):
    def test_estimators(self):
        c = Ctx()
        self.assertEqual(translate_line("equation e1.tsls y c x @ c z1 z2", c),
                         ['bundle e1 = ev_tsls("y c x @ c z1 z2", dataset)'])
        self.assertEqual(translate_line("tsls(cov=white) y c x @ c z", c)[0],
                         'bundle eq_untitled1 = ev_tsls("y c x @ c z", dataset, "white")')
        self.assertEqual(translate_line("equation e2.binary(d=p) d c x", c),
                         ['bundle e2 = ev_binary("d c x", dataset, "probit")'])
        self.assertEqual(translate_line("equation e3.ardl(deplags=2, reglags=3, ic=bic) y x1 x2", c),
                         ['bundle e3 = ev_ardl("y x1 x2", dataset, 2, 3, "sic", "const")'])
        self.assertEqual(translate_line("e3.output", c), ["ev_ardlprint(&e3)"])
        self.assertEqual(translate_line("e3.boundstest", c), ["ev_boundsprint(&e3)"])
        self.assertEqual(translate_line("u = resid", c), ["series u = ev_resid(e3)"])
        with self.assertRaises(ValueError):
            translate_line("equation e4.binary(d=x) d c x", c)

    def test_views(self):
        c = Ctx()
        translate_line("equation e.ls y c x", c)
        self.assertEqual(translate_line("e.hettest(type=glejser)", c), ['bundle e_het = ev_hettest(e, "glejser", 1)'])
        self.assertEqual(translate_line("e.white", c), ['bundle e_het = ev_hettest(e, "white", 1)'])
        self.assertEqual(translate_line("e.reset(2)", c), ["bundle e_reset = ev_reset(e, 2)"])
        self.assertEqual(translate_line("e.chow 1990q1 2000q1", c), ['bundle e_chow = ev_chow(e, "1990:1 2000:1", 0)'])
        self.assertEqual(translate_line("e.chow(f) 2010q1", c), ['bundle e_chow = ev_chow(e, "2010:1", 1)'])
        self.assertEqual(translate_line("e.testadd z w", c), ['bundle e_test = ev_testadd(e, dataset, "z w")'])
        self.assertEqual(translate_line("e.testdrop x", c), ['bundle e_test = ev_testdrop(e, "x")'])
        self.assertEqual(translate_line("e.rls(q)", c), ["bundle e_rls = ev_rls(e)", 'ev_rlsplot(e_rls, "q")'])


class Structure(unittest.TestCase):
    def test_subroutine_and_call(self):
        prg = """call twice(gdp, 3, "out")
subroutine twice(series x, scalar !k, string %nm)
  series {%nm}_new = x * !k
endsub
"""
        h, todos = translate(prg)
        self.assertIn("series out_new = gdp * 3", h)
        self.assertEqual(todos, [])
        h, todos = translate("call nothere(1)\n")
        self.assertEqual(len(todos), 1)

    def test_return_in_subroutine(self):
        prg = """subroutine safe(series x)
  if @min(x) <= 0 then
    return
  endif
  series lx = log(x)
endsub
call safe(gdp)
"""
        h, todos = translate(prg)
        self.assertEqual(todos, [])
        self.assertIn("loop 1", h)
        self.assertIn("break", h)
        prg2 = "subroutine s2(series x)\nfor !i = 1 to 3\nreturn\nnext\nendsub\ncall s2(gdp)\n"
        self.assertEqual(len(translate(prg2)[1]), 1)

    def test_nested_calls(self):
        prg = """subroutine a(series x)
  call b(x)
endsub
subroutine b(series y)
  series z = y + 1
endsub
call a(cons)
"""
        self.assertIn("series z = cons + 1", translate(prg)[0])

    def test_include(self):
        import os, tempfile
        from evprg2hansl import translate_full
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "lib.prg"), "w") as f:
            f.write("subroutine sq(series x)\n  series x2 = x^2\nendsub\n")
        h, todos, _ = translate_full('include "lib"\ncall sq(gdp)\n', base_dir=d)
        self.assertIn("series x2 = gdp^2", h)
        self.assertEqual(todos, [])
        h, todos, _ = translate_full("include nofile\n", base_dir=d)
        self.assertEqual(len(todos), 1)

    def test_group_elements(self):
        c = Ctx()
        translate_line("group VaR a b", c)
        translate_line("group Q qa qb", c)
        self.assertEqual(translate_line("Q(!i)=y<VaR(!i)", c),
                         ["strings ev_nms = varnames(Q)", "string ev_nm = ev_nms[i]", "series @ev_nm = y<VaR[i]"])

    def test_misc(self):
        self.assertEqual(tl("scalar q=@qnorm(alpha)"), ["scalar q = invcdf(z, alpha)"])
        self.assertEqual(tl("scalar T=@obssmpl"), ["scalar T = $nobs"])
        self.assertEqual(tl("sort(a) du")[-1], "dataset sortby du")
        self.assertEqual(tl("delete a b"), ["catch delete a", "catch delete b"])
        self.assertEqual(tl("save \\\\tsclient\\D\\sp500.wf1"), ['store "sp500.gdt"'])
        self.assertEqual(tl("stop"), ["quit"])
        with self.assertRaises(Ignored):
            tl('cd "U:\\x"')


class NewFeatures(unittest.TestCase):
    def test_forecast(self):
        c = Ctx()
        translate_line("equation eq1.ls y c y(-1) x", c)
        self.assertEqual(translate_line("eq1.forecast yf yf_se", c),
                         ["bundle eq1_fc = ev_forecast(eq1, dataset, 1, 1, 1)",
                          "series yf = ev_fcast_series(eq1_fc, eq1_fc.level)",
                          "series yf_se = ev_fcast_se(eq1_fc, eq1_fc.level)"])
        out = translate_line("eq1.forecast(s, e, g, d) yf", c)
        self.assertEqual(out[0], "bundle eq1_fc = ev_forecast(eq1, dataset, 0, 0, 0)")
        self.assertEqual(out[-1], "ev_fplot(&eq1_fc)")

    def test_var(self):
        c = Ctx()
        out = translate_line("var v1.ls 1 2 dlog(cons) gdp @ c ffr", c)
        self.assertEqual(out, ["scalar ev_s1 = $t1", "scalar ev_s2 = $t2", "smpl full",
                               "series ev_v1 = ldiff(cons)", "smpl ev_s1 ev_s2",
                               'bundle v1 = ev_varest("1 2 ev_v1 gdp @ c ffr", dataset, 0, "dlog(cons) gdp ffr")'])
        self.assertEqual(translate_line("var v2.ls 1 4 y1 y2", c),
                         ['bundle v2 = ev_varest("1 4 y1 y2", dataset, 0, "y1 y2")'])
        self.assertEqual(translate_line("v1.impulse(12)", c), ["ev_varirfplot(v1, 12)"])
        self.assertEqual(translate_line("v1.decomp(8)", c), ["matrix v1_decomp = ev_vardecomp(v1, 8)"])
        self.assertEqual(translate_line("v1.testexog", c), ["matrix v1_granger = ev_vargranger(v1)"])
        self.assertEqual(translate_line("v1.laglen(6)", c), ["ev_varlaglen(v1, dataset, 6)"])
        self.assertEqual(translate_line("v1.makeresids r1 r2", c),
                         ["series r1 = ev_varresid(v1, 1)", "series r2 = ev_varresid(v1, 2)"])

    def test_databases(self):
        c = Ctx()
        self.assertEqual(translate_line("store(d=macro) gdp cons", c),
                         ['store "macro.bin" gdp cons --database --overwrite'])
        with self.assertRaises(Ignored):
            translate_line("dbopen other.edb", c)
        self.assertEqual(translate_line("fetch gdp", c), ['open "other.bin" --quiet', "data gdp --quiet"])
        with self.assertRaises(ValueError):
            translate_line("fetch gdp", Ctx())

    def test_pages(self):
        c = Ctx()
        translate_line("wfcreate(wf=w, page=quarterly) q 1990 1999", c)
        translate_line("group g1 a b", c)
        out = translate_line("pagecreate(page=annual) a 1990 1999", c)
        self.assertEqual(out, ["string ev_pagedir = $dotdir", "smpl full", 'store "@ev_pagedir/quarterly.gdtb"', "nulldata 10 --preserve",
                               "setobs 1 1990 --time-series", "scalar ev_N = $nobs"])
        out = translate_line("pageselect quarterly", c)
        self.assertEqual(out, ["string ev_pagedir = $dotdir", "smpl full", 'store "@ev_pagedir/annual.gdtb"',
                               'open "@ev_pagedir/quarterly.gdtb" --quiet --preserve', "scalar ev_N = $nobs",
                               "list g1 = a b"])
        self.assertTrue(c.need_pages)


class Estimators(unittest.TestCase):
    def test_explicit_and_arma_pass_through(self):
        self.assertEqual(tl("equation e.ls y = c(1) + c(2)*x"), ['bundle e = ev_ls("y = c(1) + c(2)*x", dataset)'])
        self.assertEqual(tl("ls y c x ar(1) ma(1)"), ['bundle eq_untitled1 = ev_ls("y c x ar(1) ma(1)", dataset)'])

    def test_system(self):
        c = Ctx()
        translate_line("system s1", c)
        translate_line("s1.append dlog(cons) = c(1) + c(2)*dlog(gdp)", c)
        translate_line("s1.append dlog(inv) = c(3) + c(2)*dlog(gdp) - c(4)*ffr", c)
        translate_line("s1.append inst ffr(-1) dlog(gdp(-1))", c)
        out = translate_line("s1.3sls", c)
        self.assertEqual(out[0], 'strings ev_sd = defarray("dlog(cons)", "dlog(inv)")')
        self.assertEqual(out[1], 'strings ev_sx = defarray("c dlog(gdp)", "c dlog(gdp) (-(ffr))")')
        self.assertEqual(out[2], 'strings ev_sc = defarray("1 2", "3 2 4")')
        self.assertEqual(out[4], 'bundle s1 = ev_system(ev_sd, ev_sx, ev_sc, dataset, "3sls", "ffr(-1) dlog(gdp(-1))", 1, ev_st, -1)')
        self.assertEqual(translate_line("s1.makeresids r1 r2", c)[1], "series r2 = ev_sysresid(s1, 2)")
        c2 = Ctx()
        translate_line("system s2", c2)
        translate_line("s2.append y = c(1)*exp(c(2)*x)", c2)
        self.assertIn("ev_nlsystem", translate_line("s2.sur", c2)[1])   # nonlinear: own estimator

    def test_vec_and_coint(self):
        c = Ctx()
        out = translate_line("var v1.ec(d, 2) 1 3 lc lg ly", c)
        self.assertEqual(out, ['bundle v1 = ev_vecm("1 3 lc lg ly", dataset, "d", 2, 0, "lc lg ly")'])
        self.assertEqual(translate_line("v1.impulse(6)", c), ["ev_varirfplot(v1, 6)"])
        self.assertEqual(translate_line("v1.output", c), ["ev_vecprint(&v1)"])
        self.assertEqual(translate_line("v1.coint(c, 4)", c), ['ev_coint("lc lg ly", dataset, "c", 4)'])
        translate_line("group g lc lg", c)
        self.assertEqual(translate_line("g.coint(b, 2)", c), ['ev_coint("lc lg", dataset, "b", 2)'])


class Advanced(unittest.TestCase):
    def test_fiml_and_gmm(self):
        c = Ctx()
        translate_line("system s", c)
        translate_line("s.append y1 = c(1) + c(2)*y2 + c(3)*x1", c)
        translate_line("s.append y2 = c(4) + c(2)*y1 + c(5)*x2", c)
        out = translate_line("s.fiml", c)
        self.assertIn("s_fs_s <- system".replace("s_fs_s", "ev_fs_s"), out)
        self.assertIn("  equation y1 const y2 x1", out)
        self.assertIn("  endog y1 y2", out)
        self.assertIn("  b[1,2] - b[2,2] = 0", out)
        self.assertTrue(any(x.startswith('bundle s = ev_sysfrom("fiml"') and "{1, 2, 3, 4, 6}" in x for x in out))
        c2 = Ctx()
        translate_line("system g", c2)
        translate_line("g.append y = c(1) + c(2)*x", c2)
        translate_line("g.append inst z", c2)
        self.assertIn('"gmm"', translate_line("g.gmm", c2)[4])

    def test_matrix_and_svar(self):
        c = Ctx()
        translate_line("var v.ls 1 2 a b", c)
        self.assertEqual(translate_line("matrix(2,2) pa", c), ["matrix pa = zeros(2, 2)"])
        self.assertEqual(translate_line("pa.fill(b=r) 1, 0, na, 1", c), ["matrix pa = mshape({1, 0, NA, 1}, 2, 2)'"])
        self.assertEqual(translate_line("pa(2,1) = na", c), ["pa[2,1] = NA"])
        translate_line("matrix(2,2) pb", c)
        self.assertEqual(translate_line("v.svar(rtype=patsr, namea=pa, nameb=pb)", c), ["ev_svar(&v, pa, pb)"])
        self.assertEqual(translate_line("v.svar(lr)", c), ["ev_svar_lr(&v)"])

    def test_model(self):
        c = Ctx()
        translate_line("equation ec.ls dlog(cons) c dlog(gdp)", c)
        translate_line("equation ei.ls inv c gdp(-1)", c)
        translate_line("model m", c)
        translate_line("m.merge ec ei", c)
        translate_line("m.append @identity gdp = cons + inv + g", c)
        out = translate_line("m.solve(d=s)", c)
        self.assertEqual(out[0], "bundles ev_mb = defarray(ec, ei)")
        self.assertEqual(out[3], "bundle m = ev_modelsolve(ev_mb, ev_mi, dataset, 0, 0, ev_mo)")
        self.assertEqual(out[4:], ["series cons_0 = ev_modelseries(m, 1)", "series inv_0 = ev_modelseries(m, 2)",
                                   "series gdp_0 = ev_modelseries(m, 3)"])


class Remaining(unittest.TestCase):
    def test_nonlinear_system_and_hac(self):
        c = Ctx()
        translate_line("system s", c)
        translate_line("s.append y = c(1)*x^c(2)", c)
        translate_line("s.append z = c(3)*x^c(2)", c)
        out = translate_line("s.sur", c)
        self.assertEqual(out[1], 'bundle s = ev_nlsystem(ev_se, dataset, "sur", "", 1, -1)')
        c2 = Ctx()
        translate_line("system g", c2)
        translate_line("g.append y = c(1) + c(2)*x", c2)
        translate_line("g.append inst z", c2)
        self.assertTrue(translate_line("g.gmm(w=hac)", c2)[4].endswith("ev_st, 0)"))
        with self.assertRaises(ValueError):
            translate_line("s.fiml", c)

    def test_svar_text(self):
        from evprg2hansl import svar_text
        kind, A, B = svar_text(["@e1 = c(1)*@u1", "@e2 = -c(2)*@e1 + c(3)*@u2", "@e3 = 0.5*@e1 + c(4)*@e2 + c(5)*@u3"], 3)
        self.assertEqual(kind, "ab")
        self.assertEqual(A, [[1.0, 0.0, 0.0], [None, 1.0, 0.0], [-0.5, None, 1.0]])
        self.assertEqual(B, [[None, 0.0, 0.0], [0.0, None, 0.0], [0.0, 0.0, None]])
        self.assertEqual(svar_text(["@lr1(@u2) = 0"], 2), ("lr", [1, 2]))
        self.assertEqual(svar_text(["@lr2(@u1) = 0"], 2), ("lr", [2, 1]))
        c = Ctx()
        translate_line("var v.ls 1 2 a b", c)
        translate_line("text t", c)
        translate_line("t.append @lr2(@u1) = 0", c)
        self.assertEqual(translate_line("v.svar(rtype=lrtext) t", c), ["ev_svar_lr(&v, 0, {2, 1})"])
        translate_line("matrix(2,2) lr", c)
        translate_line("lr.fill(b=r) na, 0, na, na", c)
        self.assertEqual(translate_line("v.svar(rtype=patlr, namelr=lr)", c), ["ev_svar_lr(&v, 0, {1, 2})"])

    def test_model_options(self):
        c = Ctx()
        translate_line("equation ec.ls dlog(cons) c dlog(gdp)", c)
        translate_line("model m", c)
        translate_line("m.merge ec", c)
        translate_line("m.append gdp = cons + g", c)
        self.assertEqual(translate_line("m.addinit(v=n) @all", c), ["series cons_a = ev_eqres(ec, dataset)"])
        translate_line('m.scenario "Scenario 1"', c)
        translate_line("m.override g", c)
        out = translate_line("m.solve(s=s, r=50)", c)
        self.assertEqual(out[2], 'bundle ev_mo = _(overrides = defarray("g"), suffix = "_1", addfactors = 1, reps = 50)')
        self.assertIn("series cons_1 = ev_modelseries(m, 1)", out)
        self.assertIn('series gdp_1s = ev_modelseries(m, 2, "sd")', out)


class Program(unittest.TestCase):
    def test_loop_and_if_blocks(self):
        prg = "for !i = 1 to 3\n series x{!i} = !i\nnext\nif !i = 3 then\n !a = 1\nendif\n"
        out, todos = translate(prg)
        self.assertIn("loop i = 1..3\n    series x$i = i\nendloop", out)
        self.assertIn("if i == 3\n    scalar a = 1\nendif", out)
        self.assertEqual(todos, [])

    def test_continuation_and_comments(self):
        prg = "' header\nequation e.ls y c _\n  x  ' trailing\n"
        out, _ = translate(prg)
        self.assertIn("# header", out)
        self.assertIn('bundle e = ev_ls("y c   x", dataset)', out)

    def test_todo_reported(self):
        out, todos = translate("sys1.fiml\n")
        self.assertEqual(todos, [(1, "sys1.fiml")])
        self.assertIn("# TODO(EViews line 1", out)


if __name__ == "__main__":
    unittest.main()
