#!/usr/bin/env python3
"""Enhancement-340: compiling the same source twice produced two different MIRs.

A module instantiated with named port connections whose actuals are UNDECLARED
names gets those names declared implicitly (Enhancement-41). The declaration was
emitted while walking the instance's port bindings -- which live in a HashMap.
Rust seeds its hashers randomly PER PROCESS, so the walk order varied run to run,
and with it which implicit net was declared first. That set the string-interner
ids, which set the node numbering, which set the SSA value numbering.

`examples/lrm_examples/va/lrm_p150_1.va` produced 2 distinct MIRs and
`lrm_p209_1.va` produced 8, about half the runs each.

NOT a miscompile -- the permutation is consistent, and the simulated output was
byte-identical across variants (verified: 417 transient rows, same hash, before
and after this fix). But builds were not reproducible, and it defeated MIR-diff
output-preservation checking: a change under test could not be distinguished from
the compiler disagreeing with itself.

Fixed by walking the bindings in the TARGET's declared port order, which is both
deterministic and the order a reader expects, with the port name as a total
tie-break.

  [1] the same source compiles to the SAME MIR every time
  [2] and so do the two corpus models that exhibited this
  [3] the resulting model still simulates, and to the expected values
"""
import hashlib
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

NOISE = re.compile(r"^\s*(Finished building .* in .*s|Finished .*|Compiling .*)\s*$")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def mir_hashes(path, n=12):
    """Hash the MIR dump n times; a correct compiler yields ONE distinct value."""
    hs = set()
    with tempfile.TemporaryDirectory() as t:
        for _ in range(n):
            r = subprocess.run([OPENVAF, "--dump-mir", path, "-o",
                                os.path.join(t, "o.osdi")],
                               capture_output=True, text=True, timeout=180)
            txt = "\n".join(l for l in (r.stdout + r.stderr).splitlines()
                            if not NOISE.match(l))
            hs.add(hashlib.md5(txt.encode()).hexdigest())
    return hs


def main():
    # [1] the committed reproducer
    hs = mir_hashes(os.path.join(HERE, "twoimplicit.va"))
    check("two implicit nets on one instance compile to the SAME MIR every time",
          len(hs) == 1, f"{len(hs)} distinct over 12 compilations")

    # [2] the two corpus models that showed it
    for rel, was in (("examples/lrm_examples/va/lrm_p150_1.va", 2),
                     ("examples/lrm_examples/ams/lrm_p209_1.va", 8)):
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            check(f"{os.path.basename(rel)} is deterministic", False, "missing")
            continue
        hs = mir_hashes(p)
        check(f"{os.path.basename(rel)} is deterministic (was {was} distinct)",
              len(hs) == 1, f"{len(hs)} distinct over 12 compilations")

    # [3] and it still simulates correctly
    osdi = os.path.join(HERE, "twoimplicit.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, "twoimplicit.va"), "-o", osdi],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        check("the model compiles and simulates", False, f"rc={r.returncode}")
    else:
        deck = os.path.join(HERE, "_det.cir")
        with open(deck, "w") as f:
            f.write("determinism\nVp p 0 dc 1\nVq q 0 dc 0\n"
                    "N1 p q m\n.model m twoimplicit\n"
                    f".control\npre_osdi {os.path.basename(osdi)}\nop\n"
                    "print i(vp)\n.endc\n.end\n")
        try:
            o = subprocess.run([NGSPICE, "-b", os.path.basename(deck)], cwd=HERE,
                               capture_output=True, text=True, timeout=180)
            t = o.stdout + o.stderr
            sig = o.returncode
        finally:
            for q in (deck, osdi):
                if os.path.exists(q):
                    os.remove(q)
        m = re.search(r"i\(vp\)\s*=\s*([-\d.eE+]+)", t)
        got = float(m.group(1)) if m else None
        # n_a sees 1 mS to p and 2 mS to q, so it sits at 1/3 V; n_b sees 2 mS to p
        # and 1 mS to q, so it sits at 2/3 V. Current out of p is therefore
        #   1m*(1 - 1/3) + 2m*(1 - 2/3) = 4/3 mA -- the divider matters.
        check("the model still simulates (I = 4/3 mA through the two dividers)",
              # relative tolerance: ngspice prints 6 significant digits, so an
              # absolute 1e-9 bound is tighter than the printed value can express
              sig >= 0 and got is not None
              and abs(abs(got) - 4.0e-3 / 3.0) < 1e-5 * (4.0e-3 / 3.0),
              f"i(vp)={got}")

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
