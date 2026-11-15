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
                         ["bundle eq1_fc = ev_forecast(eq1, dataset, 0, 1)", "series f10_fit = ev_fcast_series(eq1_fc)"])
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
        with self.assertRaises(ValueError):
            translate_line("equation eq2.arch(1,1,t) yy c", c)

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
                         ["bundle eq1_fc = ev_forecast(eq1, dataset, 1, 1)",
                          "series yf = ev_fcast_series(eq1_fc)", "series yf_se = ev_fcast_se(eq1_fc)"])
        out = translate_line("eq1.forecast(s, e, g) yf", c)
        self.assertEqual(out[0], "bundle eq1_fc = ev_forecast(eq1, dataset, 0, 0)")
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
