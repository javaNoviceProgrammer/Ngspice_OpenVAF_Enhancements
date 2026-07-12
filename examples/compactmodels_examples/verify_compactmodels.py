#!/usr/bin/env python3
"""
Enhancement-159: real production compact-model bring-up (BSIM4 + EKV).

This exercises actual industry CMC (Compact Model Coalition) Verilog-A models --
the ones people tape out with -- through the full openvaf-r -> OSDI -> ngspice
path, and validates their physics. The model sources are the CMC reference decks
bundled with OpenVAF (`OpenVAF-master-20260610/integration_tests/`); they are
compiled here, not copied, so their licenses stay in place.

**BSIM4** (the industry-standard bulk MOSFET, ~12.6k lines of Verilog-A) is
validated against ngspice's *built-in* BSIM4 -- a rigorous self-check, since both
are the same model: the OSDI-compiled BSIM4.8 and the native BSIM4.8.3 agree to a
few percent across the I-V family (the residual is the point-release version gap).

A real finding surfaced during bring-up: OSDI keeps every internal node **static**
(no dynamic node collapsing), so BSIM4's internal drain/source nodes (`di`/`si`)
must be *connected*. With the default `rdsmod=0` the model leaves them floating and
the device conducts **zero current**; enabling the external series-resistance nodes
with `rdsmod=1` (the model near-shorts them when no S/D geometry is given) connects
them and the device works. This is the documented way to use these OSDI MOSFET
models.

**EKV** (EPFL's compact MOSFET, ~840 lines) is a model ngspice has *no* built-in
for -- so OSDI genuinely extends ngspice's device set -- and it works out of the
box (no rdsmod wrinkle); its physics are checked directly.

Checks (each under BOTH the Sparse and KLU solvers):
  [1] BSIM4 compiles through openvaf-r and loads in ngspice.
  [2] with rdsmod=1 the OSDI BSIM4 conducts a physical current.
  [3] finding: with the default rdsmod=0 the internal S/D nodes float -> Id=0.
  [4] the OSDI BSIM4 output family (Id-Vds) matches built-in BSIM4 to <5%.
  [5] the OSDI BSIM4 transfer curve (Id-Vgs) matches built-in BSIM4 to <6%.
  [6] EKV compiles, conducts, and is physical: Id rises with Vgs and saturates in
      Vds.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))            # repo root
sys.path.insert(0, os.path.dirname(HERE))                # examples/ (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers
check_both_solvers(__file__)   # re-execs under BOTH solvers, injecting .option

ITEST = os.path.join(ROOT, "OpenVAF-master-20260610", "integration_tests")
BSIM4_VA = os.path.join(ITEST, "BSIM4", "bsim4.va")
EKV_VA = os.path.join(ITEST, "EKV", "ekv.va")

SCRATCH = tempfile.mkdtemp(prefix="cmodel_verify_")
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_va(src, out):
    r = subprocess.run([OPENVAF, src, "-o", os.path.join(SCRATCH, out)],
                       capture_output=True, text=True, timeout=300, cwd=SCRATCH)
    return r.stdout + r.stderr, os.path.exists(os.path.join(SCRATCH, out))


def run_deck(name, deck):
    with open(os.path.join(SCRATCH, name), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True,
                       timeout=180, cwd=SCRATCH)
    return r.stdout + r.stderr


def read_cols(fname):
    rows = []
    p = os.path.join(SCRATCH, fname)
    if not os.path.exists(p):
        return rows
    for ln in open(p):
        f = ln.split()
        if f:
            rows.append([float(x) for x in f])
    return rows


# ---------------------------------------------------------------------------
out, ok = compile_va(BSIM4_VA, "bsim4.osdi")
check("[1] BSIM4 (industry MOSFET, 12.6k lines) compiles + loads via OSDI", ok,
      "" if ok else out.strip().splitlines()[-1:])
if not ok:
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1)

# [2]/[3] rdsmod=1 conducts; default rdsmod=0 floats internal nodes -> 0
log = run_deck("b4op.cir", """* bsim4 conduction
.control
pre_osdi bsim4.osdi
.endc
Vd d 0 dc 0.6
Vg g 0 dc 1.0
N1 d g 0 0 mon
Nz z g 0 0 moff
Vz z 0 dc 0.6
Vgz gz 0 dc 1.0
.model mon  bsim4va w=10u l=1u rdsmod=1 rsh=1
.model moff bsim4va w=10u l=1u
.op
.control
run
set numdgt=8
print i(vd) i(vz)
.endc
.end
""")
i_on = abs(float((re.search(r"i\(vd\)\s*=\s*(-?[0-9.eE+-]+)", log) or [0, "nan"]).group(1)
                 if re.search(r"i\(vd\)\s*=\s*(-?[0-9.eE+-]+)", log) else "nan"))
m_off = re.search(r"i\(vz\)\s*=\s*(-?[0-9.eE+-]+)", log)
i_off = abs(float(m_off.group(1))) if m_off else float("nan")
check("[2] BSIM4 with rdsmod=1 conducts a physical current", i_on > 1e-4,
      f"(Id = {i_on*1e3:.3f} mA)")
check("[3] finding: default rdsmod=0 floats internal S/D nodes -> Id=0", i_off < 1e-12,
      f"(Id = {i_off:.2e} A)")

# [4] output family Id-Vds match to built-in
run_deck("b4out.cir", """* bsim4 out family
.control
pre_osdi bsim4.osdi
.endc
Vg g 0 dc 1.0
Vd d 0 dc 0.6
Vmb d db 0
M1 db g 0 0 nb W=10u L=1u
.model nb nmos level=54 version=4.8.2 rdsmod=1 rsh=1
Vmo d do 0
N1 do g 0 0 no
.model no bsim4va w=10u l=1u rdsmod=1 rsh=1
.dc Vd 0 1.2 0.05 Vg 0.4 1.2 0.4
.control
run
wrdata b4out.dat abs(i(vmb)) abs(i(vmo))
.endc
.end
""")
rows = read_cols("b4out.dat")
mx = max((abs(o - b) / b for b, o in ((r[1], r[3]) for r in rows) if b > 1e-7), default=1)
check("[4] OSDI BSIM4 output family matches built-in BSIM4 to <5%", mx < 0.05,
      f"(max reldiff {mx*100:.2f}%)")

# [5] transfer Id-Vgs match
run_deck("b4tr.cir", """* bsim4 transfer
.control
pre_osdi bsim4.osdi
.endc
Vg g 0 dc 0
Vd d 0 dc 0.6
Vmb d db 0
M1 db g 0 0 nb W=10u L=1u
.model nb nmos level=54 version=4.8.2 rdsmod=1 rsh=1
Vmo d do 0
N1 do g 0 0 no
.model no bsim4va w=10u l=1u rdsmod=1 rsh=1
.dc Vg 0 1.2 0.1
.control
run
wrdata b4tr.dat abs(i(vmb)) abs(i(vmo))
.endc
.end
""")
rows = read_cols("b4tr.dat")
mxt = max((abs(o - b) / b for b, o in ((r[1], r[3]) for r in rows) if b > 1e-7), default=1)
check("[5] OSDI BSIM4 transfer curve matches built-in BSIM4 to <6%", mxt < 0.06,
      f"(max reldiff {mxt*100:.2f}%)")

# [6] EKV physics (no built-in reference; model ngspice lacks natively)
out, ok = compile_va(EKV_VA, "ekv.osdi")
if not ok:
    check("[6] EKV compiles", False, out.strip().splitlines()[-1:])
else:
    run_deck("ekv.dat.cir", """* ekv i-v
.control
pre_osdi ekv.osdi
.endc
Vg g 0 dc 1.0
Vd d 0 dc 0
N1 d g 0 0 em
.model em ekv_va
.dc Vd 0 1.5 0.1 Vg 0.5 1.5 0.5
.control
run
wrdata ekv.dat abs(i(vd))
.endc
.end
""")
    r = read_cols("ekv.dat")
    # three Vgs sub-sweeps of 16 points each (Vd 0..1.5 step 0.1)
    n = 16
    if len(r) >= 3 * n:
        vgs_lo = r[n - 1][1]           # Vgs=0.5, Vds=1.5
        vgs_mid = r[2 * n - 1][1]      # Vgs=1.0, Vds=1.5
        vgs_hi = r[3 * n - 1][1]       # Vgs=1.5, Vds=1.5
        # saturation: Id at Vds=0.7 vs Vds=1.5 (same high Vgs) nearly flat
        id_lowvds = r[2 * n + 7][1]    # Vgs=1.5, Vds~0.7
        id_hivds = r[3 * n - 1][1]     # Vgs=1.5, Vds=1.5
        mono = vgs_lo < vgs_mid < vgs_hi
        sat = id_hivds > id_lowvds and (id_hivds - id_lowvds) / id_hivds < 0.2
        check("[6] EKV (no ngspice built-in) conducts, rises with Vgs, saturates in Vds",
              mono and sat,
              f"(Id @Vgs 0.5/1.0/1.5 = {vgs_lo:.2e}/{vgs_mid:.2e}/{vgs_hi:.2e} A)")
    else:
        check("[6] EKV I-V produced data", False, f"({len(r)} rows)")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
