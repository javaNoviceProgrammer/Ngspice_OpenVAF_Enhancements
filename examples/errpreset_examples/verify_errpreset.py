#!/usr/bin/env python3
"""
verify_errpreset.py -- Enhancement-110: `.option errpreset=conservative|
moderate|liberal`, a single knob that sets a coordinated group of accuracy /
robustness options, end-to-end through the committed ngspice.

  [1] the three presets take effect: on an adaptive-stepping transient the
      accepted time-point count strictly orders conservative > moderate >=
      liberal (tighter tolerances -> finer stepping);
  [2] `moderate` is backward compatible: it reproduces ngspice's historical
      defaults exactly (same point count as no errpreset at all);
  [3] an explicit .option OVERRIDES the preset, regardless of .options order:
      `errpreset=liberal reltol=1e-4` and `reltol=1e-4 errpreset=liberal`
      give the SAME result, and both differ from plain liberal;
  [4] loosening works too: `errpreset=conservative reltol=1e-2` drops well
      below plain conservative;
  [5] an unknown preset warns and is ignored (the run still completes).

The point count is a clean, monotonic proxy for the coordinated tolerances:
this deck's step size is set by the LTE controller (trtol/reltol), not by a
fixed print interval. errpreset is a simulator-side feature, so no Verilog-A
model is needed.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

checks = 0
passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))

DECK = """errpreset verify
v1  in  0   pulse(0 1 5n 0.1n 0.1n 200n 400n)
r1  in  mid 1k
c1  mid 0   0.2p
r2  mid out 1k
c2  out 0   0.2p
{opts}
.tran 10n 800n
.control
run
let np = length(time)
print np
.endc
.end
"""

def run(opts):
    """Return (npoints, full_output) for a given .options line ('' = none)."""
    line = f".option {opts}" if opts else "* no options"
    p = os.path.join(HERE, "_tmp.cir")
    with open(p, "w") as f:
        f.write(DECK.format(opts=line))
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=60)
    os.remove(p)
    full = r.stdout + r.stderr
    m = re.search(r"np\s*=\s*([0-9.eE+]+)", full)
    n = int(float(m.group(1))) if m else -1
    return n, full


def main():
    print("Enhancement-110: errpreset coordinated accuracy presets")

    cons, _ = run("errpreset=conservative")
    mod,  _ = run("errpreset=moderate")
    lib,  _ = run("errpreset=liberal")
    dflt, _ = run("")   # no errpreset at all
    print(f"  (points: conservative={cons}, moderate={mod}, liberal={lib}, default={dflt})")

    # [1] presets order the stepping
    check("conservative refines more than liberal", cons > lib, f"{cons} > {lib}")
    check("conservative refines more than moderate", cons > mod, f"{cons} > {mod}")
    check("moderate at least as fine as liberal", mod >= lib, f"{mod} >= {lib}")

    # [2] moderate == historical default
    check("moderate reproduces the default (backward compatible)", mod == dflt,
          f"{mod} == {dflt}")

    # [3] explicit override, order-independent
    a, _ = run("errpreset=liberal reltol=1e-4")
    b, _ = run("reltol=1e-4 errpreset=liberal")
    check("explicit reltol override is order-independent", a == b, f"{a} == {b}")
    check("explicit reltol override changes the liberal result", a != lib,
          f"{a} != {lib}")

    # [4] loosening a preset
    loose, _ = run("errpreset=conservative reltol=1e-2")
    check("explicit loose reltol overrides conservative", loose < cons,
          f"{loose} < {cons}")

    # [5] unknown preset warns, run still completes
    n_bad, out_bad = run("errpreset=bogus")
    check("unknown preset warns", "unknown errpreset" in out_bad.lower())
    check("unknown preset still completes the run", n_bad > 0, f"points={n_bad}")

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


if __name__ == "__main__":
    main()
