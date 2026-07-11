#!/usr/bin/env python3
"""
Enhancement-157: device aging (reliability degradation flow) -- `aging` command.

`aging <t_target>` ages every aging-capable device in the loaded circuit to a
target operating lifetime and re-stamps the circuit, so any analysis run
afterwards sees the degraded devices. A device opts in by exposing, in its
Verilog-A / OSDI model, a degradation-RATE operating-point variable (`agerate`)
and a per-instance AGE parameter (`age`); the engine integrates the rate into a
dose and writes it into `age`, and the model owns the physics that maps `age` to
a parameter shift. Here the demo model `agemos` is a square-law NMOS with an
NBTI-style threshold shift  dVth = dvth_ref*(age/age_ref)^n .

Checks (each under BOTH the Sparse and KLU solvers):
  [1] enumeration -- `aging` finds exactly the two ageable NMOS and silently
      skips the resistor and the sources (no bad-parameter probes).
  [2] static degradation -- after `aging`, drain current drops, and the reported
      dose is exactly rate*t_target; the model's threshold shift matches the
      analytic NBTI power law to 5 sig figs.
  [3] monotonicity -- aging to a longer lifetime degrades strictly more.
  [4] near-threshold sensitivity -- for the same threshold shift, the device
      biased closer to threshold loses a larger FRACTION of its current (the
      known analog-reliability effect).
  [5] dynamic duty cycle -- a gate pulsed at 30% duty ages at ~0.3x the rate of
      an identically-biased DC device (time-weighted mean of the rate opvar).
  [6] no spurious aging -- a device biased below threshold accumulates age 0.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers
check_both_solvers(__file__)   # re-execs under BOTH solvers, injecting .option

SCRATCH = tempfile.mkdtemp(prefix="aging_verify_")
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_va(src):
    osdi = os.path.join(SCRATCH, os.path.splitext(src)[0] + ".osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, src), "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=SCRATCH)
    return r.stdout + r.stderr, os.path.exists(osdi)


def run_deck(name, deck):
    with open(os.path.join(SCRATCH, name), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", name],
                       capture_output=True, text=True, timeout=300, cwd=SCRATCH)
    return r.stdout + r.stderr


def grab(log, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*(-?[0-9.eE+nan-]+)", log)
    return float(m.group(1)) if m else float("nan")


out, ok = compile_va("agemos.va")
if not ok:
    check("model compiles", False, out.strip().splitlines()[-1] if out.strip() else "")
    raise SystemExit(1)

MODEL = ".model amos agemos vth0=0.5 kp=100u w=2u l=0.5u\n"

# ---------------------------------------------------------------------------
# [1] enumeration + [2] static degradation + [4] near-threshold sensitivity
# ---------------------------------------------------------------------------
# N1 hard-driven (Vgs=1.8), N2 near-threshold (Vgs=0.9); an ordinary resistor and
# the sources must be ignored by `aging`.
log = run_deck("st.cir", f"""* aging static
.control
pre_osdi agemos.osdi
.endc
Vd1 d1 0 dc 1.0
Vg1 g1 0 dc 1.8
N1 d1 g1 0 amos
Vd2 d2 0 dc 1.0
Vg2 g2 0 dc 0.9
N2 d2 g2 0 amos
R1 d1 0 1meg
{MODEL}.control
op
set numdgt=10
let i1f = @n1[ids_op]
let i2f = @n2[ids_op]
print i1f i2f
aging 3.15e8
op
print @n1[age] @n2[age] @n1[vtheff] @n2[vtheff] @n1[ids_op] @n2[ids_op]
.endc
.end
""")

# [1] exactly two devices aged, resistor/sources skipped
m = re.search(r"aging:\s+(\d+)\s+devices?\s+aged", log)
ndev = int(m.group(1)) if m else -1
check("[1] enumeration: exactly the 2 NMOS aged (R/sources skipped)", ndev == 2,
      f"(aged {ndev})")

i1f, i2f = grab(log, "i1f"), grab(log, "i2f")
age1 = grab(log, "@n1[age]")
age2 = grab(log, "@n2[age]")
vth1 = grab(log, "@n1[vtheff]")
vth2 = grab(log, "@n2[vtheff]")
i1a = grab(log, "@n1[ids_op]")
i2a = grab(log, "@n2[ids_op]")

# [2] dose is exactly rate*t : rate1 = Vgs-vth0 = 1.3, rate2 = 0.4
check("[2a] dose = rate * t_target (engine contract)",
      abs(age1 - 1.3 * 3.15e8) < 1e-3 * age1 and abs(age2 - 0.4 * 3.15e8) < 1e-3 * age2,
      f"(age1={age1:.4g}, age2={age2:.4g})")

# analytic NBTI shift  dVth = dvth_ref*(age/age_ref)^n , vth0=0.5
def vth_expect(age, dvth_ref=0.05, age_ref=1.5e8, n=0.25):
    return 0.5 + dvth_ref * (age / age_ref) ** n
check("[2b] threshold shift matches analytic NBTI law (5 sig figs)",
      abs(vth1 - vth_expect(age1)) < 1e-5 and abs(vth2 - vth_expect(age2)) < 1e-5,
      f"(vth1={vth1:.6g} vs {vth_expect(age1):.6g})")

# [2c] current drops
check("[2c] aged drain current < fresh (degradation)",
      i1a < i1f and i2a < i2f,
      f"(N1 {i1f*1e6:.2f}->{i1a*1e6:.2f} uA, N2 {i2f*1e6:.2f}->{i2a*1e6:.2f} uA)")

# [4] near-threshold device loses a larger FRACTION of its current
frac1 = (i1f - i1a) / i1f
frac2 = (i2f - i2a) / i2f
check("[4] near-threshold device degrades more in relative current",
      frac2 > frac1,
      f"(N1 -{frac1*100:.1f}%, N2 -{frac2*100:.1f}%)")

# ---------------------------------------------------------------------------
# [3] monotonicity in target lifetime
# ---------------------------------------------------------------------------
def aged_ids(t):
    log = run_deck("mono.cir", f"""* aging monotone t={t}
.control
pre_osdi agemos.osdi
.endc
Vd d 0 dc 1.0
Vg g 0 dc 1.8
N1 d g 0 amos
{MODEL}.control
aging {t:g}
op
set numdgt=10
print @n1[ids_op] @n1[vtheff]
.endc
.end
""")
    return grab(log, "@n1[ids_op]"), grab(log, "@n1[vtheff]")

i10, v10 = aged_ids(3.15e8)     # 10 years
i20, v20 = aged_ids(6.30e8)     # 20 years
i40, v40 = aged_ids(1.26e9)     # 40 years
check("[3] longer lifetime => strictly more degradation",
      v10 < v20 < v40 and i10 > i20 > i40,
      f"(Vth {v10:.4f} < {v20:.4f} < {v40:.4f})")

# ---------------------------------------------------------------------------
# [5] dynamic duty-cycle aging
# ---------------------------------------------------------------------------
log = run_deck("dyn.cir", f"""* aging dynamic duty cycle
.control
pre_osdi agemos.osdi
.endc
Vd1 d1 0 dc 1.0
Vg1 g1 0 dc 1.8
N1 d1 g1 0 amos
Vd2 d2 0 dc 1.0
Vg2 g2 0 PULSE(0 1.8 0 1n 1n 3u 10u)
N2 d2 g2 0 amos
{MODEL}.control
aging 3.15e8 dynamic 20u 0.05u
.endc
.end
""")
mrows = re.findall(r"^\s+(n\d)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)", log, re.M)
rate = {r[0]: float(r[1]) for r in mrows}
ratio = rate.get("n2", float("nan")) / rate.get("n1", float("nan")) if rate.get("n1") else float("nan")
check("[5] dynamic: 30%-duty gate ages at ~0.3x the DC device rate",
      abs(ratio - 0.30) < 0.03,
      f"(mean-rate ratio N2/N1 = {ratio:.3f})")

# ---------------------------------------------------------------------------
# [6] no spurious aging below threshold
# ---------------------------------------------------------------------------
log = run_deck("off.cir", f"""* aging: device below threshold accrues no dose
.control
pre_osdi agemos.osdi
.endc
Vd d 0 dc 1.0
Vg g 0 dc 0.3
N1 d g 0 amos
{MODEL}.control
aging 3.15e8
op
set numdgt=10
print @n1[age] @n1[vtheff]
.endc
.end
""")
check("[6] device biased below threshold accumulates age = 0",
      abs(grab(log, "@n1[age]")) < 1e-30 and abs(grab(log, "@n1[vtheff]") - 0.5) < 1e-9,
      f"(age={grab(log, '@n1[age]'):.3g}, Vth={grab(log, '@n1[vtheff]'):.6g})")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
