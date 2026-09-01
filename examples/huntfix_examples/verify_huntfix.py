#!/usr/bin/env python3
"""Bug-hunt round: the fixes outside the osdimc machinery, pinned.

  * F7 (the headline): a NOISE-ONLY current contribution must not
    reclassify a branch's voltage/current kind (LRM 4.6.4: noise is zero
    in large-signal analyses). BSIM4's access-region noise, spelled
    `I(di,d) <+ white_noise(...)` after the conditional `V(d,di) <+ 0.0`
    collapse hint, erased the collapse from the compiled topology -- the
    internal drain floated and the whole transistor conducted EXACTLY
    ZERO at every bias, silently. `hfnoise.va` is the minimal shape; the
    suite pins conduction and, when the corpus is present, stock BSIM4
    itself.
  * F3: `altermod` of a STRING parameter works (`@mm[mode] = "quad"`),
    where it used to die with `no such vector "quad"`.
  * F4: whole-array altermod gets an honest per-element guidance message
    instead of "model 'mm' has no parameter cf", and the per-element
    spelling works.
  * F10: a multi-analysis deck (.op+.ac+.tran) driven by repeated `run`
    keeps ALL its jobs -- the batch epilogue's .op save-all is no longer
    analysis-restricted, so "no data saved ... analysis not run" is gone.
  * F11 (builtin side): `alter @r1[resistance]=1e400` is refused with a
    named error instead of silently making the resistor an open circuit.
  * F12: a rawfile roundtrip of QUALIFIED cross-plot vectors keeps their
    names (`dc2.i(v1)`, `dc2.v(a)`) instead of re-wrapping them into the
    unaddressable `i(dc2.i(v1))`.
  * F19: `alter` of a model parameter through a device name points at
    `altermod` instead of denying the parameter exists.
"""

import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_hf_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_va(path, tag):
    osdi = os.path.join(HERE, f"_hf_{tag}.osdi")
    r = subprocess.run([OPENVAF, path, "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout + r.stderr, osdi


def run_deck(deck, tag, timeout=300):
    p = os.path.join(HERE, f"_hf_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def num(out, name):
    m = re.search(rf"^{re.escape(name)}\s*=\s*(\S+)", out, re.M)
    try:
        return float(m.group(1).rstrip(","))
    except (AttributeError, ValueError):
        return None


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


# ---- F7: noise-only contributions keep the branch classification -----------
print("F7 -- noise must not reclassify a branch:")
rc, out, HFN = compile_va(os.path.join(HERE, "hfnoise.va"), "noise")
check("[1] the minimal BSIM4-shaped model compiles", rc == 0)
out = run_deck(f"""hf noise pin
V1 a 0 1
N1 a 0 mm
.model mm hfnoise
.control
pre_osdi {os.path.basename(HFN)}
op
print i(v1)
.endc
.end
""", "noise")
check("[2] ...and CONDUCTS: the V<+0 collapse survives the later reversed "
      "noise line (was exactly 0)",
      close(num(out, "i(v1)"), -1e-3, 1e-9), f"{num(out, 'i(v1)')}")

B4 = os.path.join(os.path.dirname(HERE), "..",
                  "OpenVAF-master-20260610", "integration_tests", "BSIM4",
                  "bsim4.va")
if os.path.exists(B4):
    rc, out, B4O = compile_va(os.path.abspath(B4), "bsim4")
    check("[3] stock bsim4.va compiles zero-warning", rc == 0 and
          "warning" not in out.lower())
    out = run_deck(f"""bsim4 conducts
Vd d 0 1.0
Vg g 0 1.0
NX d g 0 0 mb
.model mb bsim4va(type=1 l=1u w=10u)
.control
pre_osdi {os.path.basename(B4O)}
op
print i(vd)
.endc
.end
""", "bsim4", timeout=600)
    iv = num(out, "i(vd)")
    check("[4] ...and CONDUCTS at Vgs=Vds=1 V (was exactly 0 at every bias)",
          iv is not None and iv < -1e-4, f"i(vd)={iv}")
else:
    check("[3] stock bsim4.va present", False, "corpus not found")
    check("[4] skipped", False)

# ---- F3/F4: altermod string + array parameters -----------------------------
print("\nF3/F4 -- altermod string and array parameters:")
rc, out, HFS = compile_va(os.path.join(HERE, "hfstr.va"), "str")
check("[5] the string+array model compiles", rc == 0)
out = run_deck(f"""hf string alter
V1 a 0 1
N1 a 0 mm
.model mm hfstr
.control
pre_osdi {os.path.basename(HFS)}
op
print i(v1)
altermod @mm[mode] = "quad"
op
print i(v1)
altermod @mm[cf] = [ 5.0 6.0 7.0 ]
altermod @mm[cf[0]] = 9
op
print i(v1)
.endc
.end
""", "str")
ivs = [float(m) for m in re.findall(r"^i\(v1\) = (\S+)", out, re.M)]
check('[6] altermod @mm[mode] = "quad" reaches the model (current doubles; '
      'was `no such vector "quad"`)',
      len(ivs) >= 2 and close(ivs[0], -1e-3, 1e-12) and close(ivs[1], -2e-3, 1e-12),
      f"{ivs[:2]}")
check("[7] whole-array altermod gets the per-element GUIDANCE message "
      "(was: 'has no parameter cf')",
      "is set per element" in out and "has no parameter cf" not in out)
check("[8] ...and the per-element spelling works: cf[0]=9 -> i = -18 mA",
      len(ivs) >= 3 and close(ivs[2], -18e-3, 1e-12), f"{ivs[2:]}")

# ---- F10: repeated run of a multi-analysis deck ----------------------------
print("\nF10 -- multi-analysis deck under repeated `run`:")
out = run_deck("""hf multi-run
V1 a 0 dc 1 ac 1
R1 a 0 1k
.op
.ac lin 1 1k 1k
.tran 0.1u 0.5u
.control
run
run
run
.endc
.end
""", "multirun")
check("[9] three `run`s of an .op+.ac+.tran deck lose NO jobs "
      "(was: 'no data saved ... analysis not run')",
      "no data saved" not in out)

# ---- F11: builtin alter of a non-representable number ----------------------
print("\nF11 -- non-finite alter values:")
out = run_deck("""hf alter inf
V1 a 0 1
R1 a 0 1k
.control
alter @r1[resistance] = 1e400
op
print i(v1)
.endc
.end
""", "altinf")
check("[10] `alter @r1[resistance]=1e400` is refused by name and the "
      "resistor keeps conducting (was a silent open, i=0, rc=0)",
      "is not a finite number; not applied" in out
      and close(num(out, "i(v1)"), -1e-3, 1e-12),
      f"i={num(out, 'i(v1)')}")

# ---- F12: rawfile roundtrip of qualified vectors ---------------------------
print("\nF12 -- rawfile roundtrip keeps qualified names:")
raw = os.path.join(HERE, "_hf_fam.raw")
out = run_deck(f"""hf raw roundtrip
V1 a 0 1
R1 a 0 1k
.control
dc V1 0 1 0.25
dc V1 0 1 0.5
write {os.path.basename(raw)} dc2.v(a) dc2.i(v1)
load {os.path.basename(raw)}
display
.endc
.end
""", "raw")
check("[11] qualified cross-plot vectors survive write+load un-mangled "
      "(were re-wrapped as i(dc2.i(v1)) / v(dc2.v(a)))",
      "dc2.i(v1)" in out and "dc2.v(a)" in out
      and "i(dc2.i(v1))" not in out and "v(dc2.v(a))" not in out)

# ---- F19: alter of a model parameter names the fix -------------------------
print("\nF19 -- alter/model-parameter misdirection:")
out = run_deck(f"""hf alter model param
V1 a 0 1
N1 a 0 mm
.model mm hfstr
.control
pre_osdi {os.path.basename(HFS)}
op
alter @n1[cf[0]] = 5
.endc
.end
""", "f19")
check("[12] `alter @n1[<model param>]` says it is a MODEL parameter and "
      "names the altermod spelling (was: 'no such parameter')",
      "is a MODEL parameter of model 'mm'" in out and "altermod" in out)

# ----------------------------------------------------------------------------
print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks}")
sys.exit(0 if passed == checks else 1)
