#!/usr/bin/env python3
"""verify_hicum2.py -- Enhancements 896 to 899: the built-in HICUM L2.4.0
(level=8). F2 of the analyses correctness campaign of 2026-10-16, and what
digging into it found.

The small-signal checks compare `ac` at 1 Hz with the central difference of a
three-point `dc` sweep of the same source: the derivative of the operating
point, which the Jacobian has to reproduce. The value checks compare with the
corpus's own Verilog-A HICUM L2.4.0 (hicumL2V2p4p0.va), compiled here.

E-896: the Jacobian.
  [1]  t0 = 0 (its default): ac within 1e-6 of the dc derivative (E-895:
       2.1e-2 -- the seed of the low-injection Q_0 derivative read Q_0*Vbiei)
  [2]  rbi0 > 0: within 1e-6 (E-895: 1.0e-3 -- rbi's derivatives left out
       Qjci and ibei)
  [3]  tunnelling, b-e at -2 V: the base within 1e-6 (E-895: 0.43 -- ibet's
       left out Cjei and Cjep)
  [4]  self-heating with rcx and zetarcx under KLU: within 1e-6, and the
       same as under Sparse (E-895: 3.6e-3 -- HICUMcollTempPtr bound twice)
  [5]  SOI3 with rt under KLU: its ac the same as under Sparse, no stale
       binding (E-895: -5.29 against -1.31 -- SOI3TOUT_toutPtr bound twice)
  [6]  no device's KLU binding names a matrix pointer twice in one function
E-897: values.
  [7]  latb, latl and vcbar at high current: the collector current within
       1e-4 of the Verilog-A model (E-895: 6.5e-3 -- HICQFC's own FFdVc was 0)
  [8]  the substrate transistor in saturation, flcomp at its default: its
       current within 1e-3 of the Verilog-A model (E-895: 6.3 times low --
       itss_t was given its own temperature derivative as its value)
E-898: pnp.
  [9]  a pnp with nothing but c10 and qp0 solves, the mirror of the npn
       (E-895: no operating point, NaN)
  [10] two cards rich in effects (avalanche, NQS, lateral spreading, rbi,
       the substrate transistor, self-heating, rbx/re/rcx): the pnp mirror's
       op, ac, noise and transient are the npn's, to 1e-9
  [11] the pnp within 1e-4 of the Verilog-A model's pnp
E-899: self-heating robustness.
  [12] two analyses on a circuit of a few nodes with an internal thermal node
       (E-895: "incomplete CKTunsetup()", exit)
  [13] two analyses with the thermal terminal on a node numbered past 6: the
       same temperature both times (E-895: "CKTdltNNum() removing a non
       device-local node", exit)
  [14] flsh=2 with re: solves, within 1e-4 of the Verilog-A model (E-895: no
       operating point; E-888 solved it -- the convergence test read Veie
       reversed, and E-889 made it decide)
  [15] self-heating at -120 C ambient: within 1e-4 of the Verilog-A model and
       no NaN (E-895: "The temperature limiting function received NaN", v(c)
       0.117 V for 2.998 V)
  [16] a stage whose ibeis is 1e4 times below c10/qp0 solves in at most 11
       iterations (E-895: 14; the junction started at ibeis's critical
       voltage, 1.09 V: 180 A of transfer current)

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
VA_SRC = os.path.join(ROOT, "VA_TEST", "VA-Models-main", "code", "hicum2", "vacode", "hicumL2V2p4p0.va")
WORK = tempfile.mkdtemp(prefix="hicum2_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, text):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write(text)
    try:
        r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=300)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def nums(out, *names):
    vals = []
    for n in names:
        m = re.search(r"^%s\s*=\s*(\S+?)(?:,(\S+))?\s*$" % re.escape(n), out, re.M)
        vals.append(float(m.group(1)) if m else None)
    return vals


vaosdi = os.path.join(WORK, "hicum24.osdi")
subprocess.run([OPENVAF, VA_SRC, "-o", vaosdi], capture_output=True, text=True, timeout=600)
HAVE_VA = os.path.exists(vaosdi)

TIGHT = ".option reltol=1e-12 abstol=1e-18 vntol=1e-14 itl1=2000 itl2=2000"


def stage(card, *, va=False, pnp=False, VCC=3.0, VB=0.82, RB=200.0, RC=200.0, temp=27.0, opt=TIGHT,
          ac=None, extra_ctl="", sub=False):
    """a common-emitter stage; `ac` names the source given ac 1"""
    s = -1 if pnp else 1
    if va:
        dev = "n1 c b 0 %s tj qh" % ("s" if sub else "0")
        model = ".model qh hicuml2va type=%d %s" % (s, card)
    else:
        dev = "q1 c b 0 %s qh" % ("s" if sub else "0")
        model = ".model qh %s level=8 %s" % ("pnp" if pnp else "npn", card)
    return "\n".join([
        "* hicum2 stage",
        "vcc vcc 0 dc %r%s" % (s * VCC, " ac 1" if ac == "vcc" else ""),
        "rc vcc c %r" % RC,
        "vin in 0 dc %r%s" % (s * VB, " ac 1" if ac == "vin" else ""),
        "rb in b %r" % RB,
        "vsub s 0 0" if sub else "",
        dev, model, ".temp %r" % temp, opt, ".control",
        ("pre_osdi %s" % vaosdi) if va else "",
        "set numdgt=15", extra_ctl, ".endc", ".end", ""])


def acfd(card, src="vin", node="c", h=1e-5, solver="", **kw):
    """ac at 1 Hz against the central difference of the dc operating point"""
    V0 = kw.get("VB", 0.82) if src == "vin" else kw.get("VCC", 3.0)
    s = -1 if kw.get("pnp") else 1
    ctl = "\n".join(["ac lin 1 1 1", "print v(%s)" % node, "dc %s %r %r %r" % (src, s * V0 - h, s * V0 + h, h),
                     "let lo = v(%s)[0]" % node, "let hi = v(%s)[2]" % node, "print lo hi"])
    opt = TIGHT + ("\n.option %s" % solver if solver else "")
    out = run("acfd", stage(card, ac=src, extra_ctl=ctl, opt=opt, **kw))
    acv = nums(out, "v(%s)" % node)[0]
    lo, hi = nums(out, "lo", "hi")
    if acv is None or lo is None or hi is None:
        return None, None, out
    fd = (hi - lo) / (2 * h)
    return acv, fd, out


def rel(a, b):
    return abs(a - b) / max(abs(b), 1e-30)


BASE = "c10=2e-30 qp0=2e-14"

# ---- E-896 -------------------------------------------------------------------
a, f, out = acfd(BASE)
check("[1] t0 = 0: ac at 1 Hz equals the dc derivative", a is not None and rel(a, f) < 1e-6,
      "ac %s, dc derivative %s" % (a, f))

CARD2 = BASE + " cjei0=1e-14 vdei=0.95 zei=0.5 cjci0=5e-15 vdci=0.7 zci=0.4 t0=1e-12 rbi0=10"
a, f, out = acfd(CARD2, RB=767.19, RC=1541.27, VCC=5.2254, VB=0.82338)
check("[2] rbi0 > 0: ac at 1 Hz equals the dc derivative", a is not None and rel(a, f) < 1e-6,
      "ac %s, dc derivative %s" % (a, f))

CARD3 = BASE + " ibets=1e-4 abet=10 cjei0=1e-14 vdei=0.9 zei=0.3 ajei=2.5 cjep0=1e-14 vdep=0.9 zep=0.3 ajep=2.5"
a, f, out = acfd(CARD3, node="b", VB=-2.0, VCC=1.0, RB=1e5, RC=100.0)
check("[3] tunnelling at -2 V: the base's ac equals the dc derivative", a is not None and rel(a, f) < 1e-6,
      "ac %s, dc derivative %s" % (a, f))

CARD4 = BASE + " flsh=1 rth=1000 cth=1e-13 rcx=10 zetarcx=0.8"
ak, fk, outk = acfd(CARD4, solver="klu")
asp, fsp, outs = acfd(CARD4, solver="sparse")
check("[4] self-heating with rcx and zetarcx under KLU: ac equals the dc derivative, and Sparse's ac",
      ak is not None and asp is not None and rel(ak, fk) < 1e-6 and rel(ak, asp) < 1e-9,
      "KLU ac %s, dc derivative %s, Sparse ac %s" % (ak, fk, asp))

SOI = """* SOI3 with a thermal resistance
vdd dd 0 2
rd dd d 2k
vg g 0 dc 1.2 ac 1
m1 d g 0 0 0 t nm w=20u l=1u rt=2000 ct=1e-12
.model nm nmos level=60 tof=2e-8 tob=4e-7 tb=1e-7 nsub=1e17 vto=0.5 u0=500
.option %s
.control
set numdgt=12
ac lin 1 1e6 1e6
print v(d)
.endc
.end
"""
ok_ = run("soi_k", SOI % "klu")
os_ = run("soi_s", SOI % "sparse")
vk, vs = nums(ok_, "v(d)")[0], nums(os_, "v(d)")[0]
check("[5] SOI3 with rt under KLU: ac the same as under Sparse, no stale binding",
      vk is not None and vs is not None and rel(vk, vs) < 1e-9 and "stale" not in ok_,
      "KLU %s, Sparse %s" % (vk, vs) + (", stale binding" if "stale" in ok_ else ""))

DEV = os.path.join(ROOT, "ngspice-46", "src", "spicelib", "devices")
MACROS = ("CREATE_KLU_BINDING_TABLE", "CONVERT_KLU_BINDING_TABLE_TO_COMPLEX", "CONVERT_KLU_BINDING_TABLE_TO_REAL")
dups = []
if os.path.isdir(DEV):
    for d in sorted(os.listdir(DEV)):
        if not os.path.isdir(os.path.join(DEV, d)):
            continue
        for fn in sorted(os.listdir(os.path.join(DEV, d))):
            if not fn.endswith("bindCSC.c"):
                continue
            src = open(os.path.join(DEV, d, fn), errors="replace").read()
            for macro in MACROS:
                last = {}
                for m in re.finditer(macro + r"\s*\(\s*(\w+)\s*,", src):
                    p = m.group(1)
                    # a second binding conflicts unless an else (or #else) separates the two
                    if p in last and not re.search(r"\belse\b", src[last[p]:m.start()]) \
                            and not re.search(r"\n\w[^\n]*\(", src[last[p]:m.start()]):
                        dups.append("%s %s" % (fn, p))
                    last[p] = m.end()
    check("[6] no device's KLU binding names a matrix pointer twice", not dups, "; ".join(sorted(set(dups))[:4]))
else:
    check("[6] no device's KLU binding names a matrix pointer twice (source not found, skipped)", True)

# ---- E-897 -------------------------------------------------------------------
CARD7 = (BASE + " t0=1e-12 thcs=3e-12 ahc=0.1 fthc=0.7 rci0=50 vlim=0.5 vces=0.1 vpt=5 cjci0=5e-15 vdci=0.7"
         " zci=0.4 vptci=20 latb=3 latl=0.5 vcbar=0.04 icbar=1e-3 acbar=0.05")
OPCTL = "op\nprint v(c) i(vcc)"
ob = run("lat_b", stage(CARD7, VCC=2.0, VB=0.95, RB=50.0, RC=20.0, extra_ctl=OPCTL))
ov = run("lat_v", stage(CARD7, va=True, VCC=2.0, VB=0.95, RB=50.0, RC=20.0, extra_ctl=OPCTL)) if HAVE_VA else ""
ib, iv = nums(ob, "i(vcc)")[0], nums(ov, "i(vcc)")[0]
check("[7] latb, latl and vcbar at high current: Ic within 1e-4 of the Verilog-A model",
      ib is not None and iv is not None and rel(ib, iv) < 1e-4, "built-in %s, Verilog-A %s" % (ib, iv))

CARD8 = BASE + " itss=1e-18 msf=1.02 cjci0=5e-15 vdci=0.7 zci=0.4"
SUBCTL = "op\nprint v(c) i(vsub)"
ob = run("sub_b", stage(CARD8, sub=True, VCC=1.8254, VB=0.8978, RB=18.578, RC=35.677, extra_ctl=SUBCTL))
ov = run("sub_v", stage(CARD8, va=True, sub=True, VCC=1.8254, VB=0.8978, RB=18.578, RC=35.677, extra_ctl=SUBCTL)) if HAVE_VA else ""
sb, sv = nums(ob, "i(vsub)")[0], nums(ov, "i(vsub)")[0]
check("[8] the substrate transistor in saturation: its current within 1e-3 of the Verilog-A model",
      sb is not None and sv is not None and rel(sb, sv) < 1e-3, "built-in %s, Verilog-A %s" % (sb, sv))

# ---- E-898 -------------------------------------------------------------------
on = run("pnp_n", stage(BASE, extra_ctl="op\nprint v(c) v(b)"))
op_ = run("pnp_p", stage(BASE, pnp=True, extra_ctl="op\nprint v(c) v(b)"))
cn, cp = nums(on, "v(c)")[0], nums(op_, "v(c)")[0]
check("[9] a pnp with c10 and qp0 solves, the mirror of the npn",
      cn is not None and cp is not None and rel(-cp, cn) < 1e-12, "npn %s, pnp %s" % (cn, cp))

RICH = [
    ("c10=3.79464e-30 qp0=1.78086e-14 ibeis=5.18652e-18 mbei=1.08985 ireis=6.17189e-16 mrei=2.17907 mcf=1.02879 "
     "tbhrec=2.19965e-10 favl=17.7486 qavl=3.49707e-14 kavl=0.142286 rbx=3.66881 re=1.33033 rcx=14.5532 "
     "cjei0=4.21466e-14 vdei=0.931313 zei=0.327999 ajei=1.54268 cjep0=1.01993e-16 vdep=0.930974 zep=0.358886 "
     "ajep=2.18503 cjci0=2.20347e-16 vdci=0.62466 zci=0.254006 vptci=14.5976 cjcx0=1.58056e-15 vdcx=0.661418 "
     "zcx=0.366455 vptcx=44.0662 fbcpar=0.273943 cjs0=3.63916e-15 vds=0.529944 zs=0.491948 vpts=86.7782 "
     "rci0=55.412 vlim=0.780842 vces=0.177376 vpt=8.02316 aick=0.006299 delck=2.05813 vcbar=0.0368476 "
     "icbar=0.000141944 acbar=0.0697612 cbepar=1.40041e-16 cbcpar=5.29834e-16 flnqs=1 alqf=0.270703 "
     "alit=0.185786 latb=0.350482 latl=0.0433242 zetarcx=0.342281 zetare=-0.698357 flsh=1 rth=762.753 cth=1e-13",
     dict(VB=0.6818, VCC=1.3096, RB=512.4, RC=908.4)),
    ("c10=5.98805e-30 qp0=1.069e-14 ich=0.0521119 hf0=1.22402 hfe=0.860638 hfc=0.794481 hjei=0.925445 "
     "ibeis=1.89595e-18 mbei=1.03724 ireis=1.24592e-16 mrei=1.82512 ibcis=2.29509e-16 mbci=1.04276 "
     "ibcxs=4.24907e-18 mbcx=1.05856 favl=9.6105 qavl=1.99419e-14 kavl=0.794379 rbi0=28.6338 fgeo=0.762541 "
     "fdqr0=0.145889 fcrbi=0.143969 fqi=0.990087 itss=1.72239e-19 msf=1.02091 iscs=3.268e-17 msc=1.0076 "
     "tsf=9.50443e-12 rsu=29.2116 csu=2.16986e-15 cjei0=3.38175e-14 vdei=0.914605 zei=0.462643 "
     "cjci0=4.78559e-15 vdci=0.788936 zci=0.34223 cjs0=5.90994e-16 vds=0.633731 zs=0.304513 t0=1.56318e-13 "
     "dt0h=1.76854e-13 tbvl=2.46008e-13 tef0=7.43741e-13 gtfe=1.16116 thcs=2.81311e-12 ahc=0.297248 "
     "fthc=0.883384 tr=4.35071e-10 flsh=2 rth=344.296 cth=1e-13",
     dict(VB=0.9409, VCC=1.0603, RB=28.567, RC=50.679)),
]
MIRCTL = "\n".join(["op", "print v(c) v(b)", "ac dec 2 1e3 1e10", "let acm = mag(v(c))", "let acp = ph(v(c))",
                    "print acm[0] acm[7] acm[14] acp[7] acp[14]",
                    "noise v(c) vin dec 2 1e3 1e9", "setplot noise1", "print onoise_spectrum[0] onoise_spectrum[8]",
                    "tran 1e-8 1e-6 0 1e-8", "print v(c)[50] v(c)[100]"])
worst = 0.0
bad = []
for k, (card, b) in enumerate(RICH):
    o1 = run("rich_n%d" % k, stage(card, extra_ctl=MIRCTL, opt=TIGHT.replace("1e-12", "1e-10"), **b).replace(
        "vin in 0 dc %r" % b["VB"], "vin in 0 dc %r ac 1 sin(%r 0.002 1e6)" % (b["VB"], b["VB"])))
    o2 = run("rich_p%d" % k, stage(card, pnp=True, extra_ctl=MIRCTL, opt=TIGHT.replace("1e-12", "1e-10"), **b).replace(
        "vin in 0 dc %r" % (-b["VB"]), "vin in 0 dc %r ac 1 sin(%r -0.002 1e6)" % (-b["VB"], -b["VB"])))
    names = ["v(c)", "v(b)", "acm[0]", "acm[7]", "acm[14]", "acp[7]", "acp[14]", "onoise_spectrum[0]",
             "onoise_spectrum[8]", "v(c)[50]", "v(c)[100]"]
    n1, n2 = nums(o1, *names), nums(o2, *names)
    sign = [-1, -1, 1, 1, 1, 1, 1, 1, 1, -1, -1]
    for nm, x, y, sg in zip(names, n1, n2, sign):
        if x is None or y is None:
            bad.append("card %d %s missing" % (k, nm))
            continue
        e = abs(x - sg * y) / max(abs(x), 1e-12)
        worst = max(worst, e)
        if e > 1e-9:
            bad.append("card %d %s %g vs %g" % (k, nm, x, y))
check("[10] two rich cards: the pnp mirror's op, ac, noise and transient are the npn's",
      not bad, "worst %.2g" % worst + ("; " + "; ".join(bad[:3]) if bad else ""))

ov = run("pnp_v", stage(BASE, va=True, pnp=True, extra_ctl="op\nprint v(c) v(b)")) if HAVE_VA else ""
cv = nums(ov, "v(c)")[0]
check("[11] the pnp within 1e-4 of the Verilog-A model's pnp",
      cp is not None and cv is not None and rel(cp, cv) < 1e-4, "built-in %s, Verilog-A %s" % (cp, cv))

# ---- E-899 -------------------------------------------------------------------
TWO = """* self-heating HICUM, internal thermal node, two analyses
vcc vcc 0 2
vin b 0 0.8
q1 vcc b 0 0 qh
.model qh npn level=8 c10=2e-30 qp0=2e-14 flsh=1 rth=200 cth=1e-12
.control
op
print v(b)
op
print v(b)
echo two-analyses-done
.endc
.end
"""
out = run("two", TWO)
check("[12] two analyses with an internal thermal node on a small circuit",
      "two-analyses-done" in out and "incomplete CKTunsetup" not in out,
      "incomplete CKTunsetup()" if "incomplete CKTunsetup" in out else "")

EXT = """* self-heating HICUM, thermal terminal on a node numbered past 6
vcc vcc 0 3
r1 vcc n1 10
r2 n1 n2 10
r3 n2 c 10
vin in 0 0.85
rb in b 100
q1 c b 0 0 tj qh
rth tj 0 1e6
.model qh npn level=8 c10=2e-30 qp0=2e-14 flsh=1 rth=200 cth=1e-12
.control
set numdgt=12
op
print v(tj)
op
print v(tj)
.endc
.end
"""
out = run("ext", EXT)
tj = [float(x) for x in re.findall(r"^v\(tj\)\s*=\s*(\S+)", out, re.M)]
t1, t2 = (tj + [None, None])[:2]
check("[13] two analyses with the thermal terminal past node 6: the same temperature both times",
      t1 is not None and t2 is not None and rel(t1, t2) < 1e-9 and "non device-local" not in out,
      "%s, %s" % (t1, t2) + (", CKTdltNNum() removing a non device-local node" if "non device-local" in out else ""))

CARD14 = BASE + " flsh=2 rth=1000 cth=1e-13 re=3"
ob = run("fl2_b", stage(CARD14, extra_ctl=OPCTL))
ov = run("fl2_v", stage(CARD14, va=True, extra_ctl=OPCTL)) if HAVE_VA else ""
cb, cv = nums(ob, "v(c)")[0], nums(ov, "v(c)")[0]
check("[14] flsh=2 with re: solves, within 1e-4 of the Verilog-A model",
      cb is not None and cv is not None and rel(cb, cv) < 1e-4, "built-in %s, Verilog-A %s" % (cb, cv))

CARD15 = BASE + " flsh=1 rth=1000 cth=1e-13"
ob = run("cold_b", stage(CARD15, VB=0.9, temp=-120.0, opt="", extra_ctl=OPCTL))
ov = run("cold_v", stage(CARD15, va=True, VB=0.9, temp=-120.0, opt="", extra_ctl=OPCTL)) if HAVE_VA else ""
cb, cv = nums(ob, "v(c)")[0], nums(ov, "v(c)")[0]
check("[15] self-heating at -120 C: within 1e-4 of the Verilog-A model, no NaN",
      cb is not None and cv is not None and rel(cb, cv) < 1e-4 and "NaN" not in ob,
      "built-in %s, Verilog-A %s" % (cb, cv) + (", temperature limiting NaN" if "NaN" in ob else ""))

CARD16 = BASE + " ibeis=1e-20"
out = run("start", stage(CARD16, VCC=3.0, VB=0.85, RB=100.0, RC=200.0, opt="",
                         extra_ctl="op\nprint v(c)\nrusage totiter"))
it = re.search(r"Total iterations = (\d+)", out)
it = int(it.group(1)) if it else None
check("[16] ibeis 1e4 times below c10/qp0: solves in at most 11 iterations, without an aid",
      nums(out, "v(c)")[0] is not None and it is not None and it <= 11 and "stepping" not in out,
      "%s iterations" % it)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
