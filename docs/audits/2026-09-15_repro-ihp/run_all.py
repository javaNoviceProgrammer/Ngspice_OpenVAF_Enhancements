"""Run the IHP gnucap testbenches (SPICE translations) on the repo's ngspice
with the OSDI objects build_all.py made, and compare against the gnucap
reference outputs."""
import os, re, subprocess, sys, math
HERE = os.path.dirname(os.path.abspath(__file__))
H = os.path.join(HERE, "work")          # what fetch.sh downloaded and build_all.py compiled
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NG = os.environ.get("NGSPICE_BIN", os.path.join(REPO, "ngspice-46", "build", "src", "ngspice"))
ENV = {**os.environ, "SPICE_LIB_DIR": os.path.dirname(NG)}
RUN = f"{H}/run"; os.makedirs(RUN, exist_ok=True)

def spice(tag, deck, ctl):
    path = f"{RUN}/{tag}.cir"
    open(path, "w").write(f"* ihp {tag}\n{deck}\n.control\nset noinit\nset numdgt=12\nset wr_singlescale\nset wr_vecnames\n{ctl}\nquit\n.endc\n.end\n")
    r = subprocess.run([NG, "-b", f"{tag}.cir"], capture_output=True, text=True, cwd=RUN, env=ENV, timeout=600)
    return r.stdout + r.stderr

def wr(tag):
    """columns of run/<tag>.dat written by wrdata (names on the first line)"""
    lines = open(f"{RUN}/{tag}.dat").read().strip().splitlines()
    names = lines[0].split()
    cols = {n: [] for n in names}
    for l in lines[1:]:
        for n, v in zip(names, l.split()):
            cols[n].append(float(v))
    return cols

SI = {"T": 1e12, "G": 1e9, "Meg": 1e6, "K": 1e3, "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15, "a": 1e-18}
def num(t):
    m = re.match(r"([-+]?[\d.]+(?:[eE][-+]?\d+)?)([A-Za-z]*)$", t)
    if not m: return None
    v = float(m.group(1)); s = m.group(2)
    return v * SI.get(s, 1.0) if s else v

def ref_table(path):
    """gnucap `print` table: a `#` header line then rows; returns columns"""
    names = None; cols = None
    for l in open(path):
        if l.startswith("#"):
            names = l[1:].split(); cols = {n: [] for n in names}; continue
        if names and re.match(r"\s*[-+\d.]", l):
            vals = [num(t) for t in l.split()]
            if len(vals) == len(names) + 1:
                vals = vals[1:]          # the unnamed sweep column
            if len(vals) == len(names) and None not in vals:
                for n, v in zip(names, vals): cols[n].append(v)
    return cols

def ref_measures(path):
    out = {}
    for l in open(path):
        m = re.match(r"(\w+)=\s*(\S+)", l)
        if m and num(m.group(2)) is not None: out[m.group(1)] = num(m.group(2))
    return out

def maxrel(a, b, floor=0.0):
    worst = 0.0
    for x, y in zip(a, b):
        d = abs(x - y) / max(abs(y), floor) if max(abs(y), floor) > 0 else abs(x - y)
        worst = max(worst, d)
    return worst

report = []
def rep(name, ok, detail):
    report.append((name, ok, detail)); print(f"  {'PASS' if ok else 'FAIL'}  {name}  [{detail}]")

# ------------------------------------------------------------- resistors ---
print("resistors: tb_res_basic, 1 mA into rsil / rppd / rhigh / Rparasitic")
for corner in ("typ", "bcs", "wcs"):
    deck = (".model rsil rsil\n.model rppd rppd\n.model rhigh rhigh\n.model rparasitic Rparasitic\n"
            "Ir1 0 n1 1m\nIr2 0 n2 1m\nIr3 0 n3 1m\nIr4 0 n4 1m\n"
            "n1 n1 0 0 0 rsil l=0.5u w=0.5u mm_ok=0\nn2 n2 0 0 0 rppd l=0.5u w=0.5u mm_ok=0\n"
            "n3 n3 0 0 0 rhigh l=0.96u w=0.5u mm_ok=0\nn4 n4 0 rparasitic R=100\n")
    out = spice(f"res_{corner}", deck, f"pre_osdi ../out/resistor_res_{corner}.osdi\nop\nwrdata res_{corner}.dat v(n1) v(n2) v(n3) v(n4)")
    got = wr(f"res_{corner}"); ref = ref_table(f"{H}/ref/tb_res_basic_{corner}.gc.out")
    g = [got[k][0] for k in ("v(n1)", "v(n2)", "v(n3)")]; r = [ref[k][0] for k in ("v(tb.r1)", "v(tb.r2)", "v(tb.r3)")]
    rep(f"res {corner}: rsil/rppd/rhigh", maxrel(g, r) < 1e-4, f"ngspice {['%.6g' % x for x in g]} gnucap {['%.6g' % x for x in r]} maxrel {maxrel(g, r):.1e}")
    rep(f"res {corner}: Rparasitic R=100", abs(got['v(n4)'][0] - 0.1) < 1e-6, f"ngspice {got['v(n4)'][0]:.6g} V (gnucap {ref['v(tb.r4)'][0]:.6g}: its $simparam tnom, see hunt L1)")

# ------------------------------------------------------------ capacitors ---
print("capacitors: cutoff (cmim, rfcmim), cmomi, cmomf")
RFCMIM = """.subckt cap_rfcmim PLUS MINUS bn l=7u w=7u mm_ok=0 wfeed=2u cic0=1e-18
.param sf=1e-6
.param lplate_val={(0.353158*(l/sf) + 0.485684*l/w)*1e-12}
.param lfeed_val={(6.03468 + 0.0814268*(w/sf) - 0.821243*log(wfeed/sf)/log(1.55))*1e-12}
.param lskin_val={1.18545e-12 + 6.95462e-14*(l/sf)}
.param cox_val={(0.48922 + 0.0965145*(w+l)/sf + 0.00610947*(w*l)/(sf*sf) + 0.017*(wfeed/sf)*5)*1e-15}
.param csub_val={(50.1021 + 0.277881*(w+l)/sf + 1.25023e-5*(w*l)/(sf*sf))*1e-15}
.param rsub_val={610.132 - 1.11685*(w+l)/sf + 0.00434371*(w*l)/(sf*sf)}
.param rmim_val={0.0463973 + 0.00219577*l/w + 0.961292/(wfeed/sf) + 0.00307712*(l/sf) + 0.000217076*(l/sf)*l/w}
.param rskin_val={0.154618 + 0.00702016*(l/sf)}
.param lmim_raw={lplate_val + lfeed_val - lskin_val}
.param lmim_eff={max(lmim_raw, 1e-18)}
.param rsub_eff={max(rsub_val, 10e-3)}
.param lfeed_eff={max(lfeed_val, 1e-18)}
Cic1 PLUS bn {cic0}
Cic2 MINUS bn {cic0}
Lskin PLUS n2 {lskin_val}
Rskin PLUS n2 {rskin_val}
Lmim n2 n3 {lmim_eff}
Rmim n3 n4 {rmim_val}
xcmim n4 n5 cap_cmim l={l} w={w} mm_ok={mm_ok}
Cox n5 n51 {cox_val}
Csub n51 bn {csub_val}
Rsub n51 bn {rsub_eff}
Lfeed n5 MINUS {lfeed_eff}
Rdummy n5 bn 1G
.ends
.subckt cap_cmim PLUS MINUS l=7u w=7u mm_ok=0
R1 PLUS n1 55m
ncore n1 MINUS cmim_core l={l} w={w} mm_ok={mm_ok}
.ends
.model cmim_core cmim_core
.model cmomi cmomi
.model cmomf cmomf
"""
def cutoff(tag, corner, deck_body, outs, osdi):
    ctl = f"pre_osdi ../out/{osdi}.osdi\nac dec 1000 1e6 1e9\n"
    for i, o in enumerate(outs):
        ctl += f"meas ac fcut{i+1} when vm({o})=0.707 rise=1\n"
    out = spice(tag, RFCMIM + deck_body, ctl)
    cs = []
    for i in range(len(outs)):
        m = re.search(rf"fcut{i+1}\s*=\s*(\S+)", out)
        cs.append(1.0 / (2 * math.pi * float(m.group(1)) * 1e5) if m else float("nan"))
    return cs, out
for corner in ("typ", "bcs", "wcs"):
    body = ("V1 in1 0 dc 0 ac 1\nxc1 out1 in1 cap_cmim l=70u w=10u mm_ok=0\nR1 out1 0 100k\n"
            "V2 in2 0 dc 0 ac 1\nxc2 out2 in2 0 cap_rfcmim l=70u w=10u\nR2 out2 0 100k\n")
    cs, out = cutoff(f"cap_cutoff_{corner}", corner, body, ["out1", "out2"], f"capacitor_cap_{corner}")
    refm = ref_measures(f"{H}/ref/tb_cap_cutoff_{corner}.gc.out")
    rep(f"cap cutoff {corner}: cmim 10u x 70u", abs(cs[0] - refm["C1"]) / refm["C1"] < 2e-3, f"C1 {cs[0]:.6g} F vs gnucap {refm['C1']:.6g} F")
    rep(f"cap cutoff {corner}: rfcmim 10u x 70u (RLC network)", abs(cs[1] - refm["C2"]) / refm["C2"] < 2e-3, f"C2 {cs[1]:.6g} F vs gnucap {refm['C2']:.6g} F")
for kind, inst in (("cmomi", "ncap out1 in1 0 cmomi w=5u l=5u mmin=1 mmax=5 feed=2"), ("cmomf", "ncap out1 in1 cmomf w=5u l=5u mmin=1 mmax=5")):
    cs, out = cutoff(f"cap_{kind}", "typ", f"V1 in1 0 dc 0 ac 1\n{inst}\nR1 out1 0 100k\n", ["out1"], "capacitor_cap_typ")
    refm = ref_measures(f"{H}/ref/tb_cap_{kind}_typ.gc.out")
    rep(f"cap {kind} 5u x 5u M1..M5", abs(cs[0] - refm["C1"]) / refm["C1"] < 2e-3, f"C1 {cs[0]:.6g} F vs gnucap {refm['C1']:.6g} F")

# ------------------------------------------------------------------ MOS ---
WRAP = """.subckt sg13_{k}_{t} d g s b w={w0} l={l0} ng=1 m=1 trise=0 z1=0.34e-6 z2=0.38e-6 rfmode=0
.param wmin={wmin}
.param mw={{max(w/ng, wmin)}}
.param kk={{floor(ng/2)}}
.param pp={{ng - 2*floor(ng/2)}}
.param as_={{mw*((2-pp)*z1 + (kk-1+pp)*z2)}}
.param ad_={{mw*(pp*z1 + kk*z2)}}
.param pd_={{2*(mw*(kk+1) + (2-pp)*z1 + (kk-1+pp)*z2)}}
.param ps_={{2*(mw*(kk+pp) + pp*z1 + kk*z2)}}
nm d g s b {card} rfmode={{rfmode}} w={{w}} l={{l}} ng={{ng}} mult={{m}} as={{as_}} ad={{ad_}} ps={{ps_}} pd={{pd_}} dta={{trise}} ngcon=2 delvto=0 factuo=1
.ends
"""
def mos_header(k):
    n = WRAP.format(k=k, t="nmos", w0="0.35u" if k == "lv" else "0.3u", l0="0.34u" if k == "lv" else "0.45u",
                    wmin="0.15e-6" if k == "lv" else "0.35e-6", card=f"n{k}")
    p = WRAP.format(k=k, t="pmos", w0="0.35u" if k == "lv" else "0.3u", l0="0.28u" if k == "lv" else "0.4u",
                    wmin="0.15e-6", card=f"p{k}")
    return n + p + f".model n{k} sg13g2_{k}_nmos_psp\n.model p{k} sg13g2_{k}_pmos_psp\n"

print("MOS inverters: dc transfer, 61 points, 5 corners x {lv,hv} x {psp, psp_nqs}")
INV = {"lv": ("0.28u", "0.34u", "0.35u", "0.34u"), "hv": ("2.0u", "0.4u", "1.0u", "0.45u")}
for k in ("lv", "hv"):
    for corner in ("tt", "ss", "ff", "sf", "fs"):
        for rf in (0, 1):
            pw, pl, nw, nl = INV[k]
            deck = mos_header(k) + f"vdd vdd 0 1.2\nvin in 0 0\nxp out in vdd vdd sg13_{k}_pmos w={pw} l={pl} rfmode={rf}\nxn out in 0 0 sg13_{k}_nmos w={nw} l={nl} rfmode={rf}\n"
            osdi = f"sg13g2_mos{k}{'_rf' if rf else ''}_mos{k}_{corner}"
            tag = f"inv_{k}_{corner}{'_rf' if rf else ''}"
            out = spice(tag, deck, f"pre_osdi ../out/{osdi}.osdi\ndc vin 0 1.2 0.02\nwrdata {tag}.dat v(out) i(vdd)")
            try:
                got = wr(tag)
            except Exception as e:
                rep(f"inv {k} {corner}{' rf' if rf else ''}", False, "no data: " + out.strip().splitlines()[-1][:80]); continue
            ref = ref_table(f"{H}/ref/tb_mos{k}_inv_{corner}{'_rf' if rf else ''}.gc.out")
            vo, io = got["v(out)"], got["i(vdd)"]
            rv, ri = ref["v(out)"], ref["i(tb.vdd_src)"]
            if len(vo) != len(rv):
                rep(f"inv {k} {corner}{' rf' if rf else ''}", False, f"{len(vo)} vs {len(rv)} points"); continue
            # gnucap's reference carries a supply current with the NMOS off
            # (40 nA for the PSP, 10 uA for the PSP-NQS at Vin = 0, where
            # ngspice has 0.06 nA), which pulls v(out) down at low Vin; the
            # curves are compared from the switching region on (Vin >= 0.5 V),
            # and the low-Vin difference is reported beside
            lo = 30   # Vin >= 0.6 V: past the switching point
            dv = max(abs(a - b) for a, b in zip(vo[lo:], rv[lo:]))
            # gnucap prints 0 for a current below ~1e-8 A: relative where it printed one, absolute elsewhere
            di = max([abs(a - b) / abs(b) for a, b in zip(io[lo:], ri[lo:]) if abs(b) > 1e-7] + [0.0])
            da = max([abs(a - b) for a, b in zip(io[lo:], ri[lo:]) if abs(b) <= 1e-7] + [0.0])
            dv_lo = max(abs(a - b) for a, b in zip(vo[:lo], rv[:lo]))
            rep(f"inv {k} {corner}{' rf' if rf else ''}", dv < 1e-3 and di < 2e-3 and da < 1e-7,
                f"Vin >= 0.6: max|dV(out)| {dv:.1e} V, max rel dI(vdd) {di:.1e}; Vin < 0.6: max|dV| {dv_lo:.1e} V, gnucap I(vdd) {ri[0]:.2e} A at Vin=0 vs ours {io[0]:.2e}")

print("MOS Id-Vd: vd 0..1.2 x vg 0.2..1.2, ng 1..4, nmos/pmos, {lv,hv}, {psp, psp_nqs}")
GEO = {"lv": {1: "0.3u", 2: "0.6u", 3: "0.9u", 4: "1.2u"}, "hv": {1: "0.4u", 2: "0.8u", 3: "1.2u", 4: "1.6u"}}
LEN = {("lv", "nmos"): "0.34u", ("lv", "pmos"): "0.34u", ("hv", "nmos"): "0.45u", ("hv", "pmos"): "0.4u"}
RFMODE = {}  # (k, t, ng, rf) -> rfmode as the library's .gc writes it
for k in ("lv", "hv"):
    for t in ("nmos", "pmos"):
        for ng in (1, 2, 3, 4):
            for rf in (0, 1):
                mode = rf if not (t == "pmos" and ng >= 3 and rf) else 0   # the library's pmos ng3/ng4 rf decks say rfmode(0)
                w = GEO[k][ng]; l = LEN[(k, t)]
                sgn = "" if t == "nmos" else "-"
                deck = mos_header(k) + f"vd d 0 0\nvg g 0 0\nxm d g 0 0 sg13_{k}_{t} w={w} l={l} ng={ng} rfmode={mode}\n"
                osdi = f"sg13g2_mos{k}{'_rf' if mode else ''}_mos{k}_tt"
                tag = f"idvd_{k}_{t}_ng{ng}{'_rf' if rf else ''}"
                sweep = "dc vd 0 1.2 0.02 vg 0.2 1.2 0.2" if t == "nmos" else "dc vd 0 -1.2 -0.02 vg -0.2 -1.2 -0.2"
                out = spice(tag, deck, f"pre_osdi ../out/{osdi}.osdi\n{sweep}\nwrdata {tag}.dat i(vd)")
                try:
                    got = wr(tag)
                except Exception:
                    rep(f"idvd {k} {t} ng{ng}{' rf' if rf else ''}", False, "no data: " + out.strip().splitlines()[-1][:80]); continue
                ref = ref_table(f"{H}/ref/tb_mos{k}_{t}_id_vd_ng{ng}{'_rf' if rf else ''}.gc.out")
                gi, ri = got["i(vd)"], ref["i(tb.sd)"]
                if len(gi) != len(ri):
                    rep(f"idvd {k} {t} ng{ng}{' rf' if rf else ''}", False, f"{len(gi)} vs {len(ri)} points"); continue
                imax = max(abs(x) for x in ri)
                # relative where the current is above 1e-3 of the curve's maximum
                # (gnucap prints 0 below ~1e-11 A), absolute below
                di = max(abs(a - b) / abs(b) for a, b in zip(gi, ri) if abs(b) > 1e-3 * imax)
                da = max([abs(a - b) for a, b in zip(gi, ri) if abs(b) <= 1e-3 * imax] + [0.0])
                rep(f"idvd {k} {t} ng{ng}{' rf' if rf else ''}", di < 2e-3 and da < 1e-3 * imax,
                    f"{len(gi)} pts, max rel dI {di:.1e} above 1e-3 Imax, max |dI| {da:.1e} A below; Id(end) {gi[-1]:.6g} vs {ri[-1]:.6g}")

n_ok = sum(1 for _, ok, _ in report if ok)
print(f"\n{n_ok}/{len(report)} comparisons agree")
