#!/usr/bin/env python3
"""verify_wcd.py -- Enhancement-305: worst-case distance / MPFP high-sigma.

FORM is EXACT when the performance margin is linear in u: the failure boundary is
then a hyperplane, beta is its distance from the origin, and P_fail = Phi(-beta)
with no approximation whatsoever. So a deck whose metric is an exact linear
function of its Gaussian .params has a fully analytic answer -- these checks are
against that closed form, never against a previous ngspice build.

  R = 1000 + u,  u ~ N(0,1),  spec R > 1000 + b   ->   beta = b,  P = Phi(-b)

Covered: 1-D at 3/4/5/6 sigma; a lower (-min) spec; a 2-D case where the MPFP must
land on the symmetric point u = (b/sqrt2, b/sqrt2) -- which is what shows the
gradient search finds the right DIRECTION and not merely a 1-D degenerate answer;
a nominal point that already fails (signed, negative beta); and the mean-shift
importance-sampling refinement against the same analytic tail.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

NG = NGSPICE
rows = []



def phi_bar(b):
    return 0.5 * math.erfc(b / math.sqrt(2.0))


def run(deck, name):
    with open(os.path.join(HERE, name), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NG, "-b", name], cwd=HERE, capture_output=True,
                       text=True, timeout=600, errors="replace")
    return (r.stdout or "") + (r.stderr or "")


def grab(out, pat):
    m = re.search(pat, out, re.M)
    return float(m.group(1)) if m else None


def chk(what, got, want, tol, note=""):
    if got is None:
        rows.append((what, "NO-VALUE", None, want, note)); return
    rel = abs(got - want) / (abs(want) if want else 1.0)
    rows.append((what, "ok" if rel <= tol else "MISMATCH", got, want,
                 note or f"rel={rel:.2e}"))


BETA = r"beta = ([-\d.]+) sigma"
PF = r"P\(fail\), first-order: ([-\d.eE+]+)"
NDIM = r"wcd: (\d+) statistical dimension"

# ---- 1-D linear: R = 1000 + u, spec R > 1000+b  ->  beta = b exactly -------
for b in (3.0, 4.0, 5.0, 6.0):
    out = run(f"""* wcd 1-D linear beta={b}
.param rr = agauss(1000, 1, 1)
V1 a 0 DC 1
R1 a 0 {{rr}}
.control
wcd -metric -1/i(v1) -max {1000 + b} -analysis op
.endc
.end
""", f"_l{b}.cir")
    chk(f"1-D linear beta={b}", grab(out, BETA), b, 1e-4)
    chk(f"1-D linear P=Phi(-{b})", grab(out, PF), phi_bar(b), 1e-3)

# ---- lower spec: R = 1000 + u, spec R < 1000-b -> beta = b (other side) ----
out = run("""* wcd 1-D linear, lower spec
.param rr = agauss(1000, 1, 1)
V1 a 0 DC 1
R1 a 0 {rr}
.control
wcd -metric -1/i(v1) -min 995.5 -analysis op
.endc
.end
""", "_lo.cir")
chk("1-D linear lower spec beta=4.5", grab(out, BETA), 4.5, 1e-4)
chk("1-D linear lower spec P", grab(out, PF), phi_bar(4.5), 1e-3)

# ---- 2-D linear: R = 1000 + u1 + u2, sd = sqrt(2) -> beta = 4 at spec ------
# MPFP must be the symmetric point u1 = u2 = 4/sqrt(2) = 2.8284
sp = 1000 + 4.0 * math.sqrt(2.0)
out = run(f"""* wcd 2-D linear, two independent gaussians in series
.param r1v = agauss(500, 1, 1)
.param r2v = agauss(500, 1, 1)
V1 a 0 DC 1
R1 a m {{r1v}}
R2 m 0 {{r2v}}
.control
wcd -metric -1/i(v1) -max {sp} -analysis op
.endc
.end
""", "_2d.cir")
chk("2-D linear: dimensionality found", grab(out, NDIM), 2.0, 1e-9)
chk("2-D linear beta=4", grab(out, BETA), 4.0, 1e-3)
chk("2-D linear P=Phi(-4)", grab(out, PF), phi_bar(4.0), 1e-2)
mp = re.search(r"u0=([-+\d.]+)\s+u1=([-+\d.]+)", out)
if mp:
    chk("2-D MPFP u0 = 4/sqrt2", float(mp.group(1)), 4.0 / math.sqrt(2.0), 1e-2)
    chk("2-D MPFP u1 = 4/sqrt2", float(mp.group(2)), 4.0 / math.sqrt(2.0), 1e-2)
else:
    chk("2-D MPFP coordinates", None, 4.0 / math.sqrt(2.0), 1e-2)

# ---- nominal already failing -> negative beta ------------------------------
out = run("""* wcd nominal already violates the spec
.param rr = agauss(1000, 1, 1)
V1 a 0 DC 1
R1 a 0 {rr}
.control
wcd -metric -1/i(v1) -max 997 -analysis op
.endc
.end
""", "_neg.cir")
chk("nominal fails -> beta = -3", grab(out, BETA), -3.0, 1e-3)
chk("nominal fails -> P = Phi(+3)", grab(out, PF), phi_bar(-3.0), 1e-3)

# ---- mean-shift importance sampling must agree with the analytic tail ------
out = run("""* wcd with mean-shift importance-sampling refinement
.param rr = agauss(1000, 1, 1)
V1 a 0 DC 1
R1 a 0 {rr}
.control
wcd -metric -1/i(v1) -max 1004.5 -analysis op -is 2000 -seed 1
.endc
.end
""", "_is.cir")
chk("mean-shift beta=4.5", grab(out, BETA), 4.5, 1e-4)
pis = grab(out, r"P\(fail\), mean-shift : ([-\d.eE+]+)")
chk("mean-shift P vs analytic Phi(-4.5)", pis, phi_bar(4.5), 5e-2,
    "unbiased IS estimate, 2000 samples")


# ---- MC hunt F1 (2026-09-04): a quoted metric, and one that names no vector --
# The quotes used to stay on the expression, which was then looked up as one
# vector NAME; the failed lookup scored 0 and the "margin" was fiction. Stripped
# now, like -analysis's. And a metric that resolves to nothing is refused with
# the metric named, instead of blaming the operating point.
out = run("""* wcd metric in double quotes
.param rr = agauss(1000, 1, 1)
V1 a 0 DC 1
R1 a 0 {rr}
.control
wcd -metric "-1/i(v1)" -max 1004 -analysis op
.endc
.end
""", "_q.cir")
chk('quoted -metric "-1/i(v1)" -> beta = 4', grab(out, BETA), 4.0, 1e-4)
out = run("""* wcd metric that names no vector
.param rr = agauss(1000, 1, 1)
V1 a 0 DC 1
R1 a 0 {rr}
.control
wcd -metric v(nosuch) -max 1 -analysis op
.endc
.end
""", "_nosuch.cir")
refused = ("wcd: the metric (v(nosuch)) did not resolve" in out
           and grab(out, BETA) is None
           and "did not solve at the nominal point" not in out)
chk("-metric v(nosuch): refused naming the metric, no beta, op not blamed (1=yes)",
    1.0 if refused else 0.0, 1.0, 0.0)

# ---- MC hunt F2 (2026-09-04): the importance-sampling refinement states its
# seed, an un-seeded one says a rerun repeats it, and wcd_seed is published.
out = run("""* wcd -is without a seed
.param rr = agauss(1000, 1, 1)
V1 a 0 DC 1
R1 a 0 {rr}
.control
wcd -metric -1/i(v1) -max 1004.5 -analysis op -is 200
print wcd_seed
.endc
.end
""", "_is0.cir")
stated = ("centred on the MPFP, seed 1 (default)" in out
          and "running this wcd -is again repeats" in out
          and grab(out, r"wcd_seed = ([-\d.eE+]+)") == 1.0)
chk("-is un-seeded: 'seed 1 (default)' stated, rerun note, wcd_seed = 1 (1=yes)",
    1.0 if stated else 0.0, 1.0, 0.0)

# ---- MC hunt F3 (2026-09-04): model-declared statistics are dimensions too --
# Enhancement-535 held every `.option osdimc` draw at ONE sample for the whole
# search, so a deck whose variability is entirely model-declared was refused
# ("draws no Gaussian .params -- use agauss"), and with one 1-ohm netlist
# dimension added wcd reported beta = 106.7 for a 4-sigma event. The osdimc
# applier now has a walk mode: every Gaussian statistical parameter takes
# nominal + sigma * u_k, uniforms are held, and the mean-shift refinement
# shifts those dimensions like the netlist ones.
SIG_R, SIG_DR = 25.0, 10.0
sig_tot = math.sqrt(SIG_R ** 2 + SIG_DR ** 2)                 # 26.926
r_thr = 1000.0 + 4.0 * sig_tot                                # 1107.703
imax = -1.0 / r_thr                                           # -0.902769m
rc_c = subprocess.run([OPENVAF, "wcdmc.va", "-o", "wcdmc.osdi"], cwd=HERE,
                      capture_output=True, text=True, timeout=300)
chk("wcdmc.va compiles (0 = clean)", float(rc_c.returncode), 0.0, 0.0,
    (rc_c.stdout + rc_c.stderr).strip().splitlines()[-1][:60] if rc_c.returncode else "")
OSDIMC_DECK = """* wcd over model-declared statistics only
.control
pre_osdi wcdmc.osdi
.endc
.option osdimc
V1 a 0 DC 1
N1 a 0 mm
.model mm wcdmc
.control
wcd -metric i(v1) -max %.9g -analysis op%s
echo NDIM_MODEL=$wcd_ndim_model
.endc
.end
"""
out = run(OSDIMC_DECK % (imax, ""), "_mc.cir")
chk("osdimc-only deck: 2 model-declared dimensions", grab(out, NDIM), 2.0, 0.0,
    "was refused as drawing no Gaussian .params")
chk("osdimc-only deck: beta = 4 (FORM exact, R = r + dr linear in u)",
    grab(out, BETA), 4.0, 1e-3)
held = ("1 uniform model parameter is held at nominal" in out
        and "(0 netlist .param, 2 model-declared)" in out
        and grab(out, r"NDIM_MODEL=(\d+)") == 2.0)
chk("banner splits netlist/model dims, uniform held, $wcd_ndim_model = 2 (1=yes)",
    1.0 if held else 0.0, 1.0, 0.0)
out = run("""* wcd: model-declared statistics plus one small netlist dimension
.control
pre_osdi wcdmc.osdi
.endc
.option osdimc
.param rs = agauss(1, 1, 1)
V1 a 0 DC 1
Rs a b {rs}
N1 b 0 mm
.model mm wcdmc
.control
wcd -metric i(v1) -max %.9g -analysis op
.endc
.end
""" % imax, "_mix.cir")
beta_mix = (r_thr - 1001.0) / math.sqrt(1.0 + SIG_R ** 2 + SIG_DR ** 2)   # 3.960
chk("mixed deck: 3 dimensions (1 netlist + 2 model)", grab(out, NDIM), 3.0, 0.0)
chk("mixed deck: beta on the analytic value (was 106.7)", grab(out, BETA),
    beta_mix, 1e-3)
out = run(OSDIMC_DECK % (imax, " -is 2000 -seed 1"), "_mcis.cir")
pis = grab(out, r"P\(fail\), mean-shift : ([-\d.eE+]+)")
chk("mean-shift IS over model dims vs analytic Phi(-4)", pis, phi_bar(4.0), 0.15,
    "unbiased shifted estimate, 2000 samples")
out = run("""* wcd with nothing statistical, osdimc on
.control
pre_osdi wcdmc.osdi
set osdimc
.endc
V1 a 0 DC 1
R1 a 0 1k
.control
wcd -metric i(v1) -max -0.9m -analysis op
.endc
.end
""", "_none.cir")
chk("no statistics anywhere: refusal names both sources (1=yes)",
    1.0 if "and its models declare no Gaussian statistics" in out else 0.0, 1.0, 0.0)

# ---- MC hunt F5 (2026-09-04): contradictory limits are refused at parse time
out = run("""* wcd with -max below -min
.param rr = agauss(1000, 1, 1)
V1 a 0 DC 1
R1 a 0 {rr}
.control
wcd -metric -1/i(v1) -max 990 -min 1010 -analysis op
.endc
.end
""", "_swap.cir")
chk("-max below -min: refused as contradictory, no beta (1=yes)",
    1.0 if ("the limits are contradictory" in out and grab(out, BETA) is None) else 0.0,
    1.0, 0.0)

print("Enhancement-305: worst-case distance / MPFP vs the analytic Gaussian tail")
bad = 0
for w, v, g, wt, n in rows:
    ok = (v == "ok")
    if not ok:
        bad += 1
    gs = f"{g:.8g}" if isinstance(g, float) else str(g)
    print(f"  {'PASS' if ok else 'FAIL'}  {w}  [got {gs} want {wt:.8g} {n}]")

for f in os.listdir(HERE):
    if f.startswith("_") and f.endswith(".cir"):
        os.remove(os.path.join(HERE, f))
if os.path.exists(os.path.join(HERE, "wcdmc.osdi")):
    os.remove(os.path.join(HERE, "wcdmc.osdi"))

print(f"\n{len(rows)-bad}/{len(rows)} checks passed")
print("ALL PASS" if bad == 0 else "FAILURES PRESENT")
sys.exit(0 if bad == 0 else 1)
