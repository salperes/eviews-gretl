# EViews → gretl: Gap Analizi (ana iş listesi)

Tarih: 2026-11-15 · Kapsam: EViewsCompat 0.6, evprg2hansl, evqt · Son güncelleme: Faz 1 tamamlandı

Bu belge, EViews'in bütün özellik alanlarını tek seferde listeler ve her kalemin bugünkü
durumunu verir. Bundan sonraki her iş bu listedeki bir **kimliğe** (ör. `E3`) bağlanır;
listede olmayan bir eksik "yeni kalem" olarak değil, bu belgeye eklenip öncelik alarak
girer.

## Nasıl okunur

Durum:
- ✅ **Var**: paket + çevirici (+ gerekiyorsa evqt) var ve gretl'e karşı test edildi
- 🟡 **Kısmi**: bir katmanda var ya da seçeneklerin bir kısmı eksik (eksik kısım yazılı)
- ❌ **Yok**
- ⛔ **Yapılamaz**: kapalı format ya da gretl dışı bağımlılık

Efor: **S** = gretl'de hazır komut var, yalnız eşleme + çıktı (≤ yarım gün) ·
**M** = paket fonksiyonu yazmak gerekir (1–2 gün) · **L** = yeni tahminci/nesne (3+ gün)

Öncelik: **P1** = uygulamalı makro/finans/ders programlarında sık · **P2** = orta ·
**P3** = nadir/ileri düzey

Değerlendirme yöntemi: kod envanteri (paketin public fonksiyonları, çeviricinin tanıdığı
komut/metotlar, evqt menüleri) EViews 13 komut referansının nesne/metot listesiyle
karşılaştırıldı. EViews'in kendisiyle sayısal karşılaştırma yapılmadı (EViews yok);
"test edildi" gretl'in yerleşik komutlarına karşı demektir.

## Özet

| Alan | ✅ | 🟡 | ❌ | ⛔ | Kalem |
|---|---|---|---|---|---|
| W · Workfile, sayfalar, veri | 6 | 3 | 5 | 2 | 16 |
| F · İfadeler ve @-fonksiyonlar | 5 | 2 | 2 | 0 | 9 |
| E · Denklem tahmincileri | 6 | 1 | 15 | 0 | 22 |
| T · Denklem testleri ve görünümleri | 9 | 1 | 7 | 0 | 17 |
| S · Seri görünümleri ve işlemleri | 6 | 0 | 10 | 0 | 16 |
| G · Grup | 4 | 2 | 3 | 0 | 9 |
| V · VAR / VEC | 7 | 2 | 3 | 0 | 12 |
| Y · Sistem ve Model | 4 | 1 | 3 | 0 | 8 |
| O · Diğer nesneler | 3 | 1 | 7 | 0 | 11 |
| P · Programlama dili | 9 | 1 | 4 | 0 | 14 |
| U · Arayüz (evqt) | 9 | 2 | 5 | 1 | 17 |
| **Toplam** | **68** | **16** | **64** | **3** | **151** |

Kabaca kapsama: kalemlerin **%45'i tam, %11'i kısmi**; açık P1 kalemi 4 (W7, F5, F6, V8). Kapsanan kalemler EViews
programlarında en sık kullanılanlar olduğu için (ls, ARCH, VAR, sistemler, modeller,
döngüler, sayfalar) gerçek program kapsaması bundan yüksek: elimizdeki 6 gerçek programın
6'sı da çevrilip çalışıyor.

---

## W · Workfile, sayfalar, veri

| ID | Özellik | Durum | Eksik / not | gretl karşılığı | Efor | Öncelik |
|---|---|---|---|---|---|---|
| W1 | `wfcreate` (a/q/m/d/u), `wfopen`, `wfsave` | ✅ | kayıt .gdt olarak | open, nulldata, store | – | – |
| W2 | Dosya biçimleri: wf1/csv/xlsx/dta okuma | ✅ | | open | – | – |
| W3 | `.wf1` yazma | ⛔ | kapalı format; .gdt/.csv/.xlsx yazılır | – | – | – |
| W4 | Sayfalar: create/select/delete/rename | ✅ | | .gdtb dosyaları | – | – |
| W5 | `pagestruct` panel, `pagestack`, `pageunstack` | ✅ | | setobs --panel-vars | – | – |
| W6 | `pagestruct(freq=...)` tarihli yapı değiştirme, `pagecontract`, `pageappend` | ❌ | | setobs, dataset | S | P2 |
| W7 | **Frekans dönüştürme** sayfalar arası (`copy(c=a)`, `pagelink`, link nesneleri) | 🟡 | sayfalar arası `copy(c=…) sayfa\\seri`: a s f l x n (yüksek→düşük), r d i (düşük→yüksek); karesel/kübik eşleme (q, t, c) yok | dataset compact/expand | M | **P1** |
| W8 | `copy` (seri/nesne kopyalama, sayfalar arası) | ✅ | seri, denklem, matris, tablo, grup kopyalama | | S | P1 |
| W9 | `import`/`export` seçenekleri (Excel aralığı, sheet, names) | 🟡 | yalnız temel `import` | open --sheet/--rowoffset | S | P2 |
| W10 | `read`/`write` | 🟡 | read → append; write yok | append, store | S | P3 |
| W11 | Veritabanı .bin fetch/store, `dbopen` | ✅ | | store --database | – | – |
| W12 | EViews `.edb` veritabanı | ⛔ | kapalı format | – | – | – |
| W13 | Çevrimiçi veritabanları (`dbopen(type=fred)`, DBnomics) | ❌ | | dbnomics paketi | M | P2 |
| W14 | Alfa (metin) seriler | ❌ | | string-valued series | M | P2 |
| W15 | Değer eşlemeleri (`valmap`) | ❌ | | string-valued series | M | P3 |
| W16 | Örnek nesneleri (`sample s1 ...`, `smpl s1`) | ❌ | | smpl + kaydedilmiş koşul | S | P2 |

## F · İfadeler ve @-fonksiyonlar

| ID | Özellik | Durum | Eksik / not | gretl karşılığı | Efor | Öncelik |
|---|---|---|---|---|---|---|
| F1 | Temel matematik, dlog/d/log, @pch/@pcy, @movav/@movsum, @trend/@seas | ✅ | | | – | – |
| F2 | Örneklem istatistikleri @mean/@stdev/@var/@sum/@min/@max/@median, @obs, @elem | ✅ | | | – | – |
| F3 | Matris fonksiyonları (@inverse … @subextract), stom/mtos | ✅ | | | – | – |
| F4 | Dağılımlar | ✅ | @c/@d/@q-tdist, chisq, fdist; @rnorm @runif @rchisq @rtdist | cdf, invcdf, randgen | S | **P1** |
| F5 | **Metin fonksiyonları** @left @right @mid @len @instr @replace @upper @lower @trim @word @wcount @str @val | 🟡 | @left @right @mid @len @instr @replace @upper @lower @trim @word @wcount @str @val ve + ile birleştirme; @wfind @wkeep @wdrop @wreplace yok | substr, strstr, strsub, sprintf, atof | S | **P1** |
| F6 | **Tarih fonksiyonları** @date @dateval @datestr @day @weekday @month(t) @makedate | 🟡 | @date @day @weekday @dateval @datestr; @dateadd @datediff @makedate yok | $obsdate, isodate, epochday | M | **P1** |
| F7 | İstatistik: @cor @cov @quantile @rank @nas @cumsum türevleri (@cummax, @mstdev, @mvar) | ❌ | | corr, cov, quantile, rank | S | P2 |
| F8 | @recode, @iif, @inlist, @isna, @nan | ✅ | @recode @iif @inlist @isna @nan | ?:, missing, misszero | S | **P1** |
| F9 | Workfile bilgi fonksiyonları @wfname @pagename @ilast @ifirst @obsid | ❌ | | $datafile, $t1/$t2 | S | P2 |

## E · Denklem tahmincileri

| ID | Özellik | Durum | Eksik / not | gretl karşılığı | Efor | Öncelik |
|---|---|---|---|---|---|---|
| E1 | LS (doğrusal, açık c(i) NLS, ARMA hataları), cov=white/hac | ✅ | | ols, nls, arima | – | – |
| E2 | ARCH ailesi: GARCH/TARCH/EGARCH, ARCH-M, thrsh | ✅ | | gig + kendi ML | – | – |
| E3 | ARCH hata dağılımı t / GED, PARCH, component ARCH | 🟡 | yalnız normal | gig (t, GED) | M | P2 |
| E4 | Panel LS: pooled, FE, RE, dönem FE | ✅ | | panel | – | – |
| E5 | Dönem RE, iki yönlü RE | ❌ | | panel --random-effects (sınırlı) | M | P3 |
| E6 | **TSLS** (tek denklem, `eq.tsls y c x @ z`) | ✅ | ev_tsls: J-istatistiği, enstrüman rankı | tsls | S | **P1** |
| E7 | **GMM** tek denklem, LIML | ❌ | sistemde GMM var | gmm, tsls --liml | M | P2 |
| E8 | **BINARY** logit/probit (+ marjinal etkiler, beklenti-tahmin tablosu) | ✅ | ev_binary: logit/probit, McFadden R², LR; d=x (extreme value) yok | logit, probit | M | **P1** |
| E9 | ORDERED (sıralı logit/probit) | ❌ | | logit/probit (ordered) | S | P2 |
| E10 | CENSORED (Tobit), TRUNCATED | ❌ | | tobit, intreg | S | P2 |
| E11 | COUNT (Poisson, negatif binom) | ❌ | | poisson, negbin | S | P2 |
| E12 | HECKIT seçim modeli | ❌ | | heckit | S | P3 |
| E13 | QREG kantil regresyon | ❌ | | quantreg | S | P2 |
| E14 | ROBUSTLS, STEPLS | ❌ | | lad, omit --auto | M | P3 |
| E15 | **ARDL** (+ sınır testi, uzun dönem katsayılar, ECM) | ✅ | ev_ardl: AIC/SIC/HQ ile gecikme seçimi, uzun dönem katsayılar, PSS sınır F testi (case III asimptotik kritik değerler, k ≤ 5) | ols + kendi kodu | M | **P1** |
| E16 | COINTREG: FMOLS, DOLS, CCR | ❌ | | kendi kodu (DOLS kolay) | M | P2 |
| E17 | BREAKLS (Bai-Perron kırılmalı LS), THRESHOLD, SWITCHREG | ❌ | | kendi kodu | L | P3 |
| E18 | MIDAS | ❌ | | midasreg | M | P3 |
| E19 | GLM | ❌ | | kendi kodu | M | P3 |
| E20 | ENET / Lasso / Ridge | ❌ | | regls | M | P3 |
| E21 | Panel TSLS, dinamik panel GMM (Arellano-Bond) | ❌ | | tsls (panel), dpanel | M | P2 |
| E22 | Ağırlıklı LS (`ls(w=...)`) | ❌ | | wls | S | P2 |

## T · Denklem testleri ve görünümleri

| ID | Özellik | Durum | Eksik / not | gretl karşılığı | Efor | Öncelik |
|---|---|---|---|---|---|---|
| T1 | Wald testi | ✅ | | restrict | – | – |
| T2 | Kalıntı tanısı: Jarque-Bera, Breusch-Godfrey LM, White | ✅ | | modtest | – | – |
| T3 | Tahmin (forecast/fit) + değerlendirme tablosu, grafik | ✅ | | fcast | – | – |
| T4 | Diğer değişen varyans testleri: BPG, Harvey, Glejser, ARCH LM | ✅ | ev_hettest: BPG, Harvey, Glejser, ARCH, White | modtest --breusch-pagan, --arch | S | **P1** |
| T5 | Kalıntı korelogramı ve Q-istatistikleri (eq.correlogram, eq.correlsq) | 🟡 | seri korelogramı var, denklem görünümü yok | corrgm | S | P2 |
| T6 | **Ramsey RESET** | ✅ | ev_reset | reset | S | **P1** |
| T7 | **Chow** kırılma ve tahmin testi | ✅ | ev_chow: kırılma (çoklu tarih) ve tahmin testi | chow | S | **P1** |
| T8 | Eklenen/çıkarılan değişken testleri (testadd, testdrop) | ✅ | ev_testadd, ev_testdrop | add, omit | S | **P1** |
| T9 | **CUSUM, CUSUMSQ, özyinelemeli katsayılar** | ✅ | ev_rls: CUSUM, CUSUMSQ (5% bant, KS yaklaşımı), özyinelemeli kalıntı ve katsayılar | cusum, rolling | M | **P1** |
| T10 | Quandt-Andrews kırılma testi | ❌ | | qlrtest | S | P2 |
| T11 | Bai-Perron çoklu kırılma testi | ❌ | | kendi kodu | L | P3 |
| T12 | VIF, katsayı varyans ayrıştırması | ❌ | | vif, bkw | S | P2 |
| T13 | Etki istatistikleri (leverage, DFFITS) | ❌ | | leverage | S | P3 |
| T14 | Güven elipsi | ❌ | | kendi kodu + plot | M | P3 |
| T15 | Panel: Hausman testi, gereksiz sabit etki testi | ❌ | | panel çıktısı ($hausman) | S | P2 |
| T16 | Katsayı kovaryans matrisi, gradyanlar görünümü | ❌ | | $vcv | S | P3 |
| T17 | Temsiller görünümü (eq.representations) | ✅ | spec/eqtext | | – | – |

## S · Seri görünümleri ve işlemleri

| ID | Özellik | Durum | Eksik / not | gretl karşılığı | Efor | Öncelik |
|---|---|---|---|---|---|---|
| S1 | Tanımlayıcı istatistik, histogram, Jarque-Bera | ✅ | | summary, normtest | – | – |
| S2 | Korelogram | ✅ | | corrgm | – | – |
| S3 | Birim kök: ADF (bilgi kriteriyle), KPSS, LLC, IPS | ✅ | | adf, kpss, levinlin | – | – |
| S4 | **Phillips-Perron** | ✅ | ev_pp: Bartlett, Newey-West otomatik bant, MacKinnon p-değerleri | kendi kodu | M | **P1** |
| S5 | DF-GLS / ERS / Ng-Perron | ❌ | | adf --gls | S | P2 |
| S6 | Kırılmalı birim kök (Zivot-Andrews vb.) | ❌ | | kendi kodu | M | P2 |
| S7 | Panel birim kök: Breitung, Hadri, Fisher-ADF/PP | ❌ | | adf (Choi zaten basıyor), kendi kodu | M | P2 |
| S8 | HP filtresi | ✅ | | hpfilt | – | – |
| S9 | Bant geçiren filtreler BK, CF | ❌ | | bkfilt, kendi kodu (CF) | S | P2 |
| S10 | **Mevsimsel düzeltme** X-13 / TRAMO-SEATS, `seas` (hareketli ortalama) | ✅ | `seas(m/a)` (hareketli ortalama) ve `x13` (gretl `deseas`; x13as repoda gömülü, `tools/setup_x13.sh` kurar; save=d10/d11; d12/d13 yok); TRAMO-SEATS programı kurulu değil |a)`) var; X-13/TRAMO-SEATS için x13as programı gerekir (gretl macOS paketinde yok) | x13a (gretl ile gelir) | M | **P1** |
| S11 | Üstel düzeltme / ETS (`smooth`, `ets`) | ❌ | | kendi kodu | M | P2 |
| S12 | Ara değer doldurma (`ipolate`) | ❌ | | kendi kodu | S | P2 |
| S13 | Eşitlik testleri, tek yönlü tablolama | ❌ | | difftest, freq | S | P3 |
| S14 | Varyans oranı, BDS testi | ❌ | | kendi kodu | M | P3 |
| S15 | Spektral analiz | ❌ | | pergm | S | P3 |
| S16 | `x.genr`/`x.resample`/`x.distplot` (kernel, QQ) | ❌ | | kdensity, qqplot | S | P2 |

## G · Grup

| ID | Özellik | Durum | Eksik / not | gretl karşılığı | Efor | Öncelik |
|---|---|---|---|---|---|---|
| G1 | Tablo, çizgi/serpme grafikleri | ✅ | | gnuplot | – | – |
| G2 | İstatistik, korelasyon/kovaryans | ✅ | | summary, corr | – | – |
| G3 | Johansen eşbütünleşme testi | ✅ | | coint2 | – | – |
| G4 | Gruplar ve eleman erişimi g(i) | 🟡 | gruplar ve g(i) var; grup üyesi olarak ifade (`group g log(x)`) yok | list | – | – |
| G5 | Granger nedensellik (grup görünümü) | 🟡 | yalnız VAR içinde | var + omit | S | P2 |
| G6 | **Engle-Granger, Phillips-Ouliaris** eşbütünleşme | ✅ | ev_cointeg: Engle-Granger (SIC gecikme), Phillips-Ouliaris; z-istatistiği için p-değeri yok | coint | S | **P1** |
| G7 | Temel bileşenler, faktör analizi | ❌ | | pca | M | P2 |
| G8 | Çapraz korelogram | ❌ | | xcorrgm | S | P3 |
| G9 | N yönlü tablolama, panel/ortak çizimler | ❌ | | xtab | S | P3 |

## V · VAR / VEC

| ID | Özellik | Durum | Eksik / not | gretl karşılığı | Efor | Öncelik |
|---|---|---|---|---|---|---|
| V1 | VAR tahmini, VEC (Johansen durumları, rank) | ✅ | | var, vecm | – | – |
| V2 | Etki-tepki, varyans ayrıştırması | ✅ | | irf | – | – |
| V3 | Granger/blok dışsallık, gecikme uzunluğu kriterleri | ✅ | | | – | – |
| V4 | Yapısal VAR: A-B, uzun dönem, metin kısıtları | ✅ | | kendi ML | – | – |
| V5 | VAR kalıntıları serileri | ✅ | | | – | – |
| V6 | Kısıtlı VEC (`v.ec(restrict)` beta/alpha kısıtları) | ❌ | | vecm + restrict | M | P2 |
| V7 | IRF güven bantları, birikimli/genelleştirilmiş IRF seçenekleri | 🟡 | nokta tahmin + Cholesky/yapısal | irf --bootstrap | M | P2 |
| V8 | **VAR kalıntı testleri**: LM otokorelasyon, normallik, White | 🟡 | LM otokorelasyon (lag h ve 1..h) ve Cholesky normallik var; White ortak testi yok | modtest (VAR) | S | **P1** |
| V9 | **AR kökleri** tablosu/grafiği (kararlılık) | ✅ | ev_varroots | $compan | S | **P1** |
| V10 | VAR tahmini (`v.forecast`, `v.makemodel`) | ✅ | ev_varfcast: dinamik/statik, MA tabanlı S.E.; `makemodel` hâlâ yok | fcast (VAR) | M | **P1** |
| V11 | Tarihsel ayrıştırma | ❌ | | kendi kodu | M | P3 |
| V12 | Bayesçi VAR | ❌ | | BVAR paketi | L | P3 |

## Y · Sistem ve Model

| ID | Özellik | Durum | Eksik / not | gretl karşılığı | Efor | Öncelik |
|---|---|---|---|---|---|---|
| Y1 | Sistem: LS WLS SUR TSLS WTSLS 3SLS GMM(+HAC) FIML, doğrusal olmayan | ✅ | | system, kendi kodu | – | – |
| Y2 | Model: denklem + özdeşlik, dinamik/statik Newton çözümü | ✅ | | kendi kodu | – | – |
| Y3 | Senaryolar, override, add factor, stokastik simülasyon | ✅ | | | – | – |
| Y4 | Wald, kalıntılar (sistem) | ✅ | | | – | – |
| Y5 | Sistem kalıntı testleri, sistem ARCH | ❌ | | kendi kodu | M | P3 |
| Y6 | Modele VAR/sistem ekleme (`makemodel`, `m.merge var`) | 🟡 | yalnız tek denklemler | | M | P2 |
| Y7 | Hedef arama / kontrol (`m.control`), çözücü seçenekleri | ❌ | | kendi kodu | M | P3 |
| Y8 | Model çözüm değerlendirme tabloları (`m.msg`, fit istatistikleri) | ❌ | | | S | P3 |

## O · Diğer nesneler

| ID | Özellik | Durum | Eksik / not | gretl karşılığı | Efor | Öncelik |
|---|---|---|---|---|---|---|
| O1 | Matris/vektör/sym/coef, skaler, string | ✅ | | | – | – |
| O2 | Text nesnesi | ✅ | yalnız SVAR kısıtları için | | – | – |
| O3 | **Table nesnesi**: `freeze` tabloya, `setcell`, `setwidth`, `t(i,j)`, csv/rtf/html kaydı | ✅ | ev_table: `table(r,c)`, `t(i,j)=`, setcell, setwidth, save(csv/txt/html), show; biçimlendirme komutları yok sayılır | outfile, matrix | M | **P1** |
| O4 | Graph nesnesi biçimlendirme (`addtext`, `axis`, `setelem`) ve `save(t=png/pdf)` | 🟡 | biçimlendirme yok sayılıyor; png kayıt var | gnuplot seçenekleri | M | P2 |
| O5 | Graph türleri: histogram, boxplot, kernel, QQ, pie, dot, seasonal | ❌ | line/bar/scat/area/spike var | gnuplot, boxplot | S | P2 |
| O6 | State space (`sspace`, Kalman) | ❌ | | kalman | L | P2 |
| O7 | LogL (özel olabilirlik) | ❌ | | mle | M | P2 |
| O8 | Pool nesnesi (`pool`, `?` serileri ile tahmin) | ❌ | pagestack ile kısmen dolaşılabilir | | L | P3 |
| O9 | Spool nesnesi | ❌ | | | M | P3 |
| O10 | Factor nesnesi | ❌ | | | L | P3 |
| O11 | svector, rowvector metotları (`@wcount` vb. ile) | ❌ | | strings | S | P2 |

## P · Programlama dili

| ID | Özellik | Durum | Eksik / not | gretl karşılığı | Efor | Öncelik |
|---|---|---|---|---|---|---|
| P1 | `for`/`next` (step), `for %s`, `while`/`wend`, `if`/`else` | ✅ | | loop, if | – | – |
| P2 | !skaler, %string, {%x} / x_!i ikamesi | ✅ | | | – | – |
| P3 | `subroutine`/`call`/`endsub`, `local` | ✅ | | satır içi açma | – | – |
| P4 | `include` | ✅ | | | – | – |
| P5 | `return` | ✅ | alt programın kendi döngüsü içinde ❌ | | – | – |
| P6 | `stop`, yorum, `_` satır devamı | ✅ | | | – | – |
| P7 | Grafik/çıktı biçimlendirme satırları yok sayılır | ✅ | | | – | – |
| P8 | `exitloop` | ✅ | → break | break | S | **P1** |
| P9 | **Program argümanları** `%0 %1`, `exec`/`run` başka program | ✅ | `--args` ile %0 %1 …; `run`/`exec prog arg…` satır içi açılır | | S | **P1** |
| P10 | `@uiprompt`, `@uiedit` vb. diyaloglar | ❌ | | | M | P3 |
| P11 | Hata yönetimi `seterr`, `@errorcount`, `setmaxerrs` | ❌ | | catch | S | P2 |
| P12 | `logmsg`, `statusline`, `tic/toc` | ❌ | | printf, $stopwatch | S | P2 |
| P13 | Döngü içinde `return` (P5'in eksiği) | ❌ | | | M | P3 |
| P14 | Nesne komutlarının seçenek ayrıştırması genel | 🟡 | tanınmayan seçenek TODO olur | | – | – |

## U · Arayüz (evqt)

| ID | Özellik | Durum | Eksik / not | Efor | Öncelik |
|---|---|---|---|---|---|
| U1 | Ana pencere, komut penceresi, çıktı günlüğü, workfile penceresi | ✅ | | – | – |
| U2 | Seri, grup, denklem, VAR, sistem, model pencereleri | ✅ | | – | – |
| U3 | Denklem diyaloğu: LS / ARCH (tüm seçenekler) / panel etkileri | ✅ | | – | – |
| U4 | Forecast, Fetch/Store, sayfa sekmeleri, stack/unstack/panel yapısı | ✅ | | – | – |
| U5 | Spreadsheet düzenleme (Edit+/-), Freeze, Save, kaydedilmemiş değişiklik uyarısı | ✅ | | – | – |
| U6 | .prg çalıştırma | ✅ | | – | – |
| U7 | Denklem diyaloğunda yöntem seçimi: TSLS, GMM, BINARY, … | 🟡 | LS, ARCH, TSLS, BINARY, ARDL, panel; diğer yöntemler E kalemleriyle gelecek | S/kalem | E ile |
| U8 | Seri görünümleri: birim kök diyaloğu (yalnız ADF), filtreler | ✅ | Unit Root Test diyaloğu: ADF, PP, KPSS; seviye/fark; sabit/trend/yok. Mevsimsel düzeltme menüsü | S | P1 |
| U9 | Grafik biçimlendirme diyaloğu (eksen, renk, metin) | ❌ | | M | P2 |
| U10 | Table nesnesi penceresi (hücre düzenleme) | ✅ | TableWindow: Edit+/- ile hücre düzenleme, Save (csv/txt/html) | M | P1 |
| U11 | Komut geçmişi kaydetme / komut penceresinden program kaydetme | ❌ | | S | P2 |
| U12 | Nesne kopyala/yapıştır, sürükle-bırak | ❌ | | M | P3 |
| U13 | Yazdırma | ❌ | | S | P3 |
| U14 | Örneklem nesnesi, değer eşlemesi pencereleri | ❌ | W15, W16 ile | M | P3 |
| U15 | Durum çubuğu: Path / DB / WF / Sample | ✅ | | – | – |
| U16 | EViews eklentileri (add-ins) | ⛔ | EViews'e özgü | – | – |
| U17 | Erişilebilirlik otomasyonu altında Qt 6.8 çökmesi | 🟡 | belgelendi; Qt sürüm yükseltmesiyle tekrar denenebilir | S | P3 |

---

## Faz 1 sonucu (2026-11-15)

25 P1 kaleminin 21'i ✅, 4'ü 🟡 (W7, F5, F6, V8); S10, x13as kurulduktan sonra tamamlandı. G4 yeni bir eksik olarak 🟡 oldu
(gruplarda ifade üyeleri). Kısmi kalanlar:
karesel/kübik frekans dönüştürme, bazı metin/tarih fonksiyonları, X-13 (x13as programı
gerekiyor), VAR White ortak testi. Bu fazda bulunup düzeltilen hatalar:
- Fetch, bir veri dosyasından seri alırken bellekteki tüm denklemleri/VAR'ları siliyordu
  (`open` → `open --preserve`).
- Panel sayfasından normal sayfaya dönünce çevirici panel modunda kalıyordu; panel bilgisi
  artık sayfa başına tutuluyor.
- Tarih fonksiyonlarında yerel saat dilimi bir günlük kaymaya yol açıyordu.

Testler: paket 266 kontrol (13 dosya), çevirici 59 birim testi, evqt 95 ekran dışı kontrol,
7 örnek program (`translator/examples/phase1.prg` Faz 1'in tamamını kullanır).

## Önerilen yol haritası

**Faz 1 — P1 kalemleri (25 kalem)**, çoğu gretl'de hazır (S):
- Denklem: E6 TSLS, E8 logit/probit, E15 ARDL + sınır testi.
- Testler: T4, T6, T7, T8, T9.
- Seri: S4 Phillips-Perron, S10 X-13 mevsimsel düzeltme.
- Eşbütünleşme ve VAR: G6 Engle-Granger, V8, V9, V10.
- Veri: W7 frekans dönüştürme, W8 copy.
- Fonksiyonlar: F4, F5, F6, F8.
- Program ve tablolar: P8, P9, O3 (+U10), U8.

**Faz 2 — P2 kalemleri (yaklaşık 45)**: kalan tahminciler (GMM, sayım/Tobit/sıralı, kantil,
FMOLS/DOLS, panel GMM), panel testleri, ek birim kök testleri, filtreler, ETS, PCA, state
space, LogL, grafik türleri ve biçimlendirme.

**Faz 3 — P3 kalemleri**: kırılma/eşik/rejim modelleri, MIDAS, GLM, ENET, BVAR, pool/spool/
factor nesneleri, value map, kontrol problemleri.

**Kapsam dışı (⛔)**: .wf1 yazma, .edb okuma, EViews add-in'leri.

## "Bitti" tanımı (her kalem için)

1. Paket fonksiyonu (gerekiyorsa) ve EViews düzeninde çıktı.
2. Çevirici eşlemesi + birim testi.
3. Gretl'in yerleşik komutuna (ya da elle hesaplamaya) karşı sayısal test.
4. Anlamlıysa evqt menü/diyalog + ekran dışı GUI testi.
5. Bu belgede durum ✅ olarak güncellenir.
