#!/usr/bin/env python3
"""Enhancement-525: hierarchy, audited against Accellera VAMS-2023
clause 6, then fixed.

What this suite pins, each against the quoted clause:

  * 6.3.1 -- a `defparam` was SILENTLY DROPPED the moment its module
    contained any generate construct: the generate rewrite rebuilt the
    item region from the typed item list, which defparam is deliberately
    not part of, and the generate-block parser had no defparam arm at all
    (the parse error was then swallowed by the re-render). Both forms
    work now -- module-scope defparam beside a generate, and defparam
    INSIDE a generate block targeting the per-iteration instance with
    genvars in its value -- and precedence over #(...) still holds.
  * 6.3.6 -- "hierarchical system parameters may be overridden using ...
    module instance parameter value assignment by name":
    #(.$mfactor(4)) and .$xposition(...) on a child instance compiled
    clean and did NOTHING. The full multiplicity transform is applied
    now: reads compose (multiplicatively for $mfactor/$hflip/$vflip,
    additively for positions), the child's flow contributions scale by
    m, its flow probes read the per-copy current back, noise scales as
    the parallel combination demands (power x m for contributed
    current), and overrides compose down the hierarchy and with the
    netlist m=. Duplicate and unknown .$ overrides are targeted errors.
  * 6.3.5 / 9.19 -- $param_given() reported FALSE for any parameter
    overridden from inside the hierarchy (flattening baked the value in
    as the new default). Instance #(...) values and defparam targets now
    report given.
  * 6.5.7.1 -- "The sizes of the ports and net need to match": a scalar
    net on a 2-bit port was accepted and silently replicated onto both
    bits; it is a compile error citing the clause now, while
    matching-width buses, part-selects and {...} concatenations connect
    exactly as before.
  * 6.3.2/6.3.3 (Syntax 6-2) -- a parameter override list is all-ordered
    or all-named; the mixed form was accepted with the positional half
    silently dropped. It is an error now, like the port-connection
    equivalent always was.
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
        if junk.startswith("_lh_"):
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


def compile_file(name):
    osdi = os.path.join(HERE, f"_lh_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_lh_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmhier\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
                f"option noacct\n{ctl}\nquit\n.endc\n.end\n")
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
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def close(a, b, rel=1e-6):
    return a is not None and abs(a - b) <= rel * max(abs(b), 1e-30)


def op_current(name, model, tag, osdi, extra=""):
    sim = run(f"V1 in 0 DC 1.0\nN1 in 0 mm{extra}\n.model mm {model}",
              "op\nprint i(v1)", tag, osdi)
    return num(sim, "i(v1)")


# ---- [1] defparam vs generate (6.3.1) --------------------------------------
print("defparam and generate coexist (LRM 6.3.1):")
for name, model, want, why in [
    ("dfgen", "dfgen", -6e-3, "defparam INSIDE generate-for: 2m*1 + 2m*2"),
    ("dfgen2", "dfgen2", -7e-3, "defparam inside generate-if"),
    ("dfdrop", "dfdrop", -8e-3, "module-scope defparam beside an unrelated generate"),
    ("dfp", "dfp", -30e-3, "defparam precedence over #(...), two levels deep"),
]:
    rc, out, osdi = compile_file(f"{name}.va")
    i = op_current(name, model, name, osdi) if rc == 0 else None
    check(f"{why}: i(v1) = {want*1e3:.0f} mA", rc == 0 and close(i, want),
          f"i={i}")

# ---- [2] hierarchical system parameters on instances (6.3.6) ---------------
print("\n#(.$mfactor(n)) / .$xposition(...) child overrides (LRM 6.3.6):")
rc, out, osdi = compile_file("mchild.va")
i = op_current("mchild", "mchild", "mc", osdi) if rc == 0 else None
check("#(.$mfactor(4)): the child's 1 mA scales to 4 mA", rc == 0 and close(i, -4e-3),
      f"i={i}")
if rc == 0:
    sim = run("V1 in 0 DC 1.0\nN1 in 0 mm m=2\n.model mm mchild",
              "op\nprint i(v1)", "mc2", osdi)
    check("...and composes with the netlist m=2: 8 mA",
          close(num(sim, "i(v1)"), -8e-3), f"{num(sim, 'i(v1)')}")

rc, out, osdi = compile_file("xpos2.va")
i = op_current("xpos2", "xpos2", "xp", osdi) if rc == 0 else None
check(".$xposition(0.005) composes additively into the read: 6 mA",
      rc == 0 and close(i, -6e-3), f"i={i}")

rc, out, osdi = compile_file("mxform.va")
check("mxform.va (probe read-back + $mfactor read) compiles", rc == 0)
if rc == 0:
    sim = run("V1 in 0 DC 1.0\nVq q 0 DC 0.0\nN1 in 0 mid q mm\nR1 mid 0 1k\n"
              ".model mm mxform", "op\nprint i(v1) v(mid) i(vq)", "mx", osdi)
    check("a flow probe reads the PER-COPY current (mirror stays 0.1 V)",
          close(num(sim, "v(mid)"), 0.1), f"{num(sim, 'v(mid)')}")
    check("$mfactor reads the composed value: 4*1m*4 = 16 mA",
          close(num(sim, "i(vq)"), 16e-3), f"{num(sim, 'i(vq)')}")
    check("total port current sums both children: 20 mA",
          close(num(sim, "i(v1)"), -20e-3), f"{num(sim, 'i(v1)')}")

rc, out, osdi = compile_file("mnest.va")
i = op_current("mnest", "mnest", "mn", osdi) if rc == 0 else None
check("nested composition: leaf under x2 under x4 is x8 (+ the mid term): "
      "8.016 mA", rc == 0 and close(i, -8.016e-3), f"i={i}")

rc, out, osdi = compile_file("mnoise2.va")
check("mnoise2.va compiles", rc == 0)
if rc == 0:
    body = ("V1 in 0 DC 0 AC 1\nR0 in 0 1k\nN1 a 0 m4\nR1 a 0 1k\n"
            "N2 b 0 m1\nR2 b 0 1k\n.model m4 mnoise2\n.model m1 mnoise1")
    sim = run(body, "noise v(a) V1 dec 1 1k 1k\nprint onoise_spectrum", "n4", osdi)
    n4 = num(sim, "onoise_spectrum")
    sim = run(body, "noise v(b) V1 dec 1 1k 1k\nprint onoise_spectrum", "n1", osdi)
    n1 = num(sim, "onoise_spectrum")
    ratio = (n4 / n1) if (n4 and n1) else None
    check("noise POWER scales x4 under .$mfactor(4): amplitude ratio ~2",
          ratio is not None and abs(ratio - 2.0) < 0.02, f"ratio={ratio}")

# ---- [3] $param_given through hierarchy (6.3.5/9.19) -----------------------
print("\n$param_given sees hierarchy overrides (LRM 6.3.5):")
rc, out, osdi = compile_file("pgh.va")
i = op_current("pgh", "pgh", "pg", osdi) if rc == 0 else None
check("overridden child reports GIVEN, sibling default does not: 10m + 1m",
      rc == 0 and close(i, -11e-3), f"i={i}")
rc, out, osdi = compile_file("pgh2.va")
i = op_current("pgh2", "pgh2", "pg2", osdi) if rc == 0 else None
check("the audit's shape: ($param_given(p1) ? p1 : 99m) with #(.p1(7m)) is 7 mA",
      rc == 0 and close(i, -7e-3), f"i={i}")

# ---- [4] connection-size checking (6.5.7.1) --------------------------------
print("\nport/net size rules (LRM 6.5.7.1):")
rc, out, osdi = compile_file("vcon_only.va")
check("a {p, q} concatenation onto a 2-bit port still connects bit-per-bit",
      rc == 0)
if rc == 0:
    sim = run("V1 a 0 DC 1.0\nV2 b 0 DC 2.0\nN1 a b out mc\nR1 out 0 1k\n"
              ".model mc vcon", "op\nprint v(out)", "vc", osdi)
    check("...and computes -(1m*1 + 2m*2)*1k = -5 V",
          close(num(sim, "v(out)"), -5.0), f"{num(sim, 'v(out)')}")

rc, out, _ = compile_file("vbad.va")
check("a SCALAR net on the 2-bit port is refused citing 6.5.7.1",
      rc != 0 and "6.5.7.1" in out,
      next((l for l in out.splitlines() if "error" in l), "")[:70])

# ---- [5] mixed override forms + .$ error paths -----------------------------
print("\noverride-list checking (Syntax 6-2, 6.3.6):")
rc, out, _ = compile_file("mixparam.va")
check("mixing positional and named parameter overrides is an error",
      rc != 0 and "mix" in out,
      next((l for l in out.splitlines() if "error" in l), "")[:70])
rc, out, _ = compile_file("sysdup.va")
check("a duplicated .$mfactor override is an error", rc != 0 and "more than once" in out)
rc, out, _ = compile_file("sysbad.va")
check("an unknown .$vt override is an error naming the legal set",
      rc != 0 and "$xposition" in out)

print(f"\n{'ALL PASS' if checks == passed else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if checks == passed else 1)
