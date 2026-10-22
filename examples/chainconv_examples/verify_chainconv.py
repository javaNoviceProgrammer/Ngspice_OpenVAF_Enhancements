#!/usr/bin/env python3
"""Enhancement-917: a non-finite step no longer slips past the compiled MOSFET limiter.

F3 and F4 of the 2026-09-26 options-and-convergence hunt. A common-source chain
of N compiled BSIM4 stages converged its operating point in 9 iterations up to
550 stages and then took 73 at 600, 184 at 1000, 93 at 3000 under KLU (363 under
Sparse), through dynamic gmin stepping, every stage at the end of the chain
printing "loaded a value that is not finite".

The first Newton step through hundreds of inverting stages overflows: the
linearised gain compounds, and the far nodes come back as +-inf. The E-543
limiter brings each device's vgs and vds back to a finite step, but judged
"did it move" by |lim - raw| > reltol*|raw| + vntol, which is inf > inf --
false -- for an infinite raw value. The device was evaluated at the overflowed
point, loaded NaN, and Newton fell to gmin stepping. A non-finite raw value now
counts as moved.

F4 (the long-chain transient rejecting 2-3x the built-in's timepoints) does not
reproduce at E-913: the rejection counts match the built-in's; check [4] keeps it so.

Checks (both solvers):
  [1] 600, 1000 and 3000 stages: the operating point in at most 12 iterations,
      no gmin stepping, nothing non-finite
  [2] ... the point the built-in BSIM4 4.8 chain reaches, to 1e-5 V
  [3] the built-in chain of 1000 stages for reference: dynamic gmin stepping
      (the compiled chain no longer needs it)
  [4] the 1000-stage transient rejects no more than 1.5x the built-in's points
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

ROOT = os.path.dirname(os.path.dirname(HERE))
BSIM4 = os.path.join(ROOT, "VA_TEST", "VA-Models-main", "code", "bsim4", "vacode", "bsim4.va")

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_bsim4():
    out = os.path.join(HERE, "bsim4va.osdi")
    if os.path.exists(out):
        os.remove(out)
    subprocess.run([OPENVAF, os.path.relpath(BSIM4, HERE), "-o", "bsim4va.osdi"], cwd=HERE,
                   capture_output=True, text=True, timeout=600)
    return os.path.exists(out)


def chain(kind, n, mode="op"):
    """N common-source stages, each driving the next gate, 20k loads (the hunt's deck)"""
    L = [f"* chainconv {kind} {n} {mode}", "vdd vdd 0 dc 1.2",
         "vin in0 0 " + ("pulse(0 1.2 1n 1n 1n 5n 10n)" if mode == "tran" else "dc 0.6")]
    for k in range(n):
        dev = f"nm{k} in{k+1} in{k} 0 0 mos_va" if kind == "va" else f"m{k} in{k+1} in{k} 0 0 mos_bi"
        L += [dev + " w=1u l=100n", f"r{k} vdd in{k+1} 20k"]
    probe = " ".join(f"v(in{k})" for k in range(1, n + 1, max(1, n // 20)))
    L += [".model mos_va bsim4va()", ".model mos_bi nmos level=14 version=4.8", ".control",
          "pre_osdi bsim4va.osdi", "set numdgt=12"]
    L += ["op", f"print {probe}"] if mode == "op" else ["tran 0.5n 20n"]
    L += ["rusage totiter traniter accept rejected", ".endc", ".end"]
    name = f"_{kind}{n}{mode}.cir"
    with open(os.path.join(HERE, name), "w") as f:
        f.write("\n".join(L) + "\n")
    p = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True, text=True,
                       timeout=900, errors="replace")
    out = p.stdout + p.stderr

    def stat(k):
        m = re.search(rf"^{k}\s*=\s*(\d+)", out, re.M)
        return int(m.group(1)) if m else None
    volts = [float(x) for x in re.findall(r"^v\(in\d+\) = (\S+)", out, re.M)]
    return {"iter": stat("Total iterations"), "titer": stat("Transient iterations"),
            "acc": stat("Accepted timepoints"), "rej": stat("Rejected timepoints"),
            "volts": volts, "gmin": "gmin stepping" in out, "nonfinite": "not finite" in out}


print("Enhancement-917: a non-finite step no longer slips past the compiled MOSFET limiter\n")
if not check("compile the VA-Models BSIM4", compile_bsim4()):
    print(f"\n{passed}/{checks} checks passed")
    sys.exit(1)

for n in (600, 1000, 3000):
    va, bi = chain("va", n), chain("bi", n)
    check(f"[1] {n} stages: the operating point in at most 12 iterations, no gmin stepping, nothing "
          "non-finite (was 73 / 184 / 93 under KLU and 363 under Sparse, through gmin stepping)",
          va["iter"] is not None and va["iter"] <= 12 and not va["gmin"] and not va["nonfinite"],
          f"{va['iter']} iterations")
    dv = max((abs(a - b) for a, b in zip(va["volts"], bi["volts"])), default=None)
    check(f"[2] {n} stages: the point of the built-in BSIM4 chain, to 1e-5 V",
          dv is not None and len(va["volts"]) == len(bi["volts"]) > 10 and dv < 1e-5, f"{dv}")
    if n == 1000:
        check("[3] (reference) the built-in chain of 1000 stages goes through dynamic gmin stepping, "
              "which the compiled chain no longer needs", bi["gmin"], f"{bi['iter']} iterations")

va, bi = chain("va", 1000, "tran"), chain("bi", 1000, "tran")
check("[4] the 1000-stage transient rejects no more than 1.5x the built-in's timepoints (the hunt's "
      "2-3x does not reproduce at E-913)",
      va["rej"] is not None and bi["rej"] and va["rej"] <= 1.5 * bi["rej"],
      f"compiled {va['titer']}/{va['acc']}/{va['rej']}, built-in {bi['titer']}/{bi['acc']}/{bi['rej']}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
