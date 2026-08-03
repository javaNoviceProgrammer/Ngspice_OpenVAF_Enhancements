#!/usr/bin/env python3
"""verify_probeshort.py -- Enhancement-406: a flow probe that silently shorts the
branch it was meant to measure.

A declared `branch (a,b) br` and the node pair `(a,b)` are DIFFERENT branches --
which is correct, and what the DAE, the E-400 contribution map and the LRM
compliance notes all agree on. The trap is what follows: probing the flow of a
branch nothing contributes to makes it an ideal ammeter (a 0 V source, E-36), so
contributing through one spelling and probing through the other drops an ammeter
in parallel with the real branch and SHORTS it.

The consequence is numeric and silent. Two 1 kOhm sections in series draw 0.5 mA;
with the first shorted they draw 1.0 mA, rc=0, no diagnostic before this release.

Passes iff:
  * the trap is REPORTED (L023) and still measurably shorted -- the lint reports,
    it does not change the semantics, because the ammeter is a documented feature
    and a model may legitimately want it;
  * the correctly spelled model is SILENT and draws the right current;
  * the deliberate sense-ammeter idiom (nothing else drives the pair) is SILENT --
    this is the false positive to avoid, and six branches in the shipped corpus
    rely on it.

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

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


OSDI = os.path.join(tempfile.gettempdir(), "probeshort.osdi")


def compile_models():
    src = os.path.join(HERE, "probe_short.va")
    r = subprocess.run([OPENVAF, src, "-o", OSDI], capture_output=True, text=True, timeout=600)
    return r.returncode == 0 and os.path.exists(OSDI), r.stdout + r.stderr


def terminal_current(model):
    """i(v1) for a 1 V source driving the device; two 1k in series => -5e-4."""
    path = os.path.join(tempfile.gettempdir(), f"ps_{model}.cir")
    with open(path, "w") as fh:
        fh.write(f"""* probeshort {model}
v1 a 0 dc 1
nd1 a 0 m{model}
.model m{model} {model}()
.control
pre_osdi {OSDI}
op
print i(v1)
.endc
.end
""")
    out = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                         timeout=120).stdout
    m = re.findall(r"i\(v1\)\s*=\s*(-?[\d.eE+-]+)", out)
    return float(m[0]) if m else None


def main():
    print("Enhancement-406: a probe-only branch shorting the branch that is driven\n")
    ok, log = compile_models()
    if not check("probe_short.va compiles", ok):
        print(f"\n{passed}/{checks} checks passed")
        return 1

    fired = [l for l in log.splitlines() if "L023" in l]
    check("the trap is REPORTED (L023)", len(fired) == 1,
          fired[0].strip()[:78] if fired else "no L023 diagnostic")
    check("the report names the probed branch `br`",
          any("`br`" in l for l in fired))
    check("`ok` is not reported", not any("module `ok`" in l for l in fired))
    check("`sense_ok` (deliberate ammeter) is not reported",
          not any("sense_ok" in l for l in fired))
    check("exactly one warning in the whole file", len(fired) == 1, f"{len(fired)} found")

    # the numeric consequence the lint exists to explain
    i_ok = terminal_current("ok")
    i_trap = terminal_current("trap")
    check("correctly spelled model draws 0.5 mA", i_ok is not None and abs(i_ok + 5e-4) < 1e-9,
          f"i(v1)={i_ok}")
    check("trap still draws 1.0 mA -- the lint reports, it does not change semantics",
          i_trap is not None and abs(i_trap + 1e-3) < 1e-9, f"i(v1)={i_trap}")
    if i_ok and i_trap:
        check("the short doubles the current", abs(abs(i_trap / i_ok) - 2.0) < 1e-6,
              f"ratio {i_trap / i_ok:.6f}")

    # suppression, so a model that means it can say so
    src = os.path.join(HERE, "probe_short.va")
    r = subprocess.run([OPENVAF, "--allow", "probe_only_branch_short", src, "-o", OSDI],
                       capture_output=True, text=True, timeout=600)
    check("--allow probe_only_branch_short silences it",
          r.returncode == 0 and "L023" not in (r.stdout + r.stderr))
    r = subprocess.run([OPENVAF, "--deny", "probe_only_branch_short", src, "-o", OSDI],
                       capture_output=True, text=True, timeout=600)
    check("--deny turns it into an error", r.returncode != 0, f"rc={r.returncode}")

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    sys.exit(main())
