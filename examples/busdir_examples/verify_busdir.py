#!/usr/bin/env python3
"""verify_busdir.py -- Enhancement-411: a descending netlist bus range binds the
nodes to a device's terminals in REVERSE order, and now says so.

THE UNDERLYING ASYMMETRY, which is what makes this worth a diagnostic:

  * The COMPILER declares a bus port's terminals in ASCENDING bit order
    whichever direction the declaration is written with. `hir_def`'s item_tree
    lowering sorts the endpoints and loops upward -- "declare from lsb to msb
    (ascending), matching natural bit order; direction of the original
    [msb:lsb] only affects range checks". So `inout [3:0] a` and
    `inout [0:3] a` produce the SAME positional terminal list.

  * The NETLIST does honour direction: Enhancement-221 expands `d[3:0]` to
    `d[3] d[2] d[1] d[0]`.

Put together, the spelling that looks most consistent -- a [3:0] model wired
`nd1 d[3:0] 0 mm`, where both sides say [3:0] -- is exactly the reversed one.
It compiled clean and simulated clean; only the answers were permuted.

Each bit carries a distinct conductance (a[k] -> (k+1) mS), so the current at a
node identifies the bit it really landed on.

WHERE THE WARNING DELIBERATELY STAYS QUIET, and why each is not the trap:
  * `.subckt` port lists -- a descending port bus is a deliberate interface
    choice that Enhancement-221 documents and busnodes_examples tests;
  * output and IC cards -- the order does not bind anything;
  * a range too wide to expand -- Enhancement-338's guard leaves it literal, so
    warning about a binding that never happened would be false;
  * explicit node lists and single-bit ranges -- nothing is reversed.

Exit code 0 = pass.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0
OSDI = os.path.join(tempfile.gettempdir(), "bus_direction.osdi")
WARN = "descending bus range"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(name, body, ctrl="op\nprint i(v0) i(v1) i(v2) i(v3)", cwd=None):
    d = cwd or tempfile.gettempdir()
    path = os.path.join(d, f"bd_{name}.cir")
    with open(path, "w") as fh:
        fh.write(f"""* busdir {name}
v0 d[0] 0 dc 1
v1 d[1] 0 dc 1
v2 d[2] 0 dc 1
v3 d[3] 0 dc 1
{body}
.control
pre_osdi {OSDI}
{ctrl}
.endc
.end
""")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=300, cwd=d)
    return r.stdout + r.stderr


def bits(out):
    """Which bit each node landed on, read back from its conductance."""
    got = []
    for k in range(4):
        m = re.findall(rf"i\(v{k}\)\s*=\s*(-?[\d.eE+-]+)", out)
        if not m:
            return None
        got.append(int(round(-float(m[0]) * 1000)) - 1)
    return got


def main():
    print("Enhancement-411: a descending netlist bus range is reported\n")
    r = subprocess.run([OPENVAF, os.path.join(HERE, "bus_direction.va"), "-o", OSDI],
                       capture_output=True, text=True, timeout=600)
    if not check("bus_direction.va compiles", r.returncode == 0 and os.path.exists(OSDI),
                 (r.stdout + r.stderr).strip().splitlines()[:1]):
        print(f"\n{passed}/{checks} checks passed")
        return 1

    print("\n  the binding itself -- declaration direction must NOT matter")
    for model, decl in (("busdesc", "[3:0]"), ("busasc", "[0:3]")):
        asc = bits(run(f"a_{model}", f"nd1 d[0:3] 0 mm\n.model mm {model}()"))
        desc = bits(run(f"d_{model}", f"nd1 d[3:0] 0 mm\n.model mm {model}()"))
        check(f"model {decl}, wired d[0:3] -> a[0],a[1],a[2],a[3]", asc == [0, 1, 2, 3], str(asc))
        check(f"model {decl}, wired d[3:0] -> a[3],a[2],a[1],a[0] (reversed)",
              desc == [3, 2, 1, 0], str(desc))
    a1 = bits(run("x1", "nd1 d[0:3] 0 mm\n.model mm busdesc()"))
    a2 = bits(run("x2", "nd1 d[0:3] 0 mm\n.model mm busasc()"))
    check("[3:0] and [0:3] declarations behave IDENTICALLY", a1 == a2 and a1 is not None,
          f"{a1} vs {a2}")

    print("\n  the warning fires exactly where the order binds")
    for lab, body, want in [
            ("descending OSDI instance line", "nd1 d[3:0] 0 mm\n.model mm busdesc()", 1),
            ("descending built-in element", "rr d[1:0] 1k\nnd1 d[0:3] 0 mm\n"
                                            ".model mm busdesc()", 1),
            ("ascending instance line", "nd1 d[0:3] 0 mm\n.model mm busdesc()", 0),
            ("explicit node list", "nd1 d[3] d[2] d[1] d[0] 0 mm\n.model mm busdesc()", 0),
            ("single-bit range d[2:2]", "nd1 d[0:3] 0 mm\n.model mm busdesc()\n"
                                        "rz d[2:2] 0 1k", 0)]:
        n = run("w_" + re.sub(r"\W", "", lab), body).count(WARN)
        check(f"{lab:32s} -> {want} warning(s)", n == want, f"got {n}")

    print("\n  and stays quiet where it does not")
    n = run("sub", "x9 d[0] d[1] sub\nnd1 d[0:3] 0 mm\n.model mm busdesc()\n"
                   ".subckt sub p[1:0]\nrs p[0] p[1] 1k\n.ends").count(WARN)
    check("`.subckt` descending PORT list is silent (E-221 tests it)", n == 0, f"got {n}")
    n = run("outcards", "nd1 d[0:3] 0 mm\n.model mm busdesc()\n.save v(d[3:0])\n"
                        ".print dc v(d[3:0])").count(WARN)
    check("output cards with v(d[3:0]) are silent", n == 0, f"got {n}")
    n = run("wide", "rw e[99999999999999999999:0] 2k\nnd1 d[0:3] 0 mm\n"
                    ".model mm busdesc()").count(WARN)
    check("a range too wide to expand is silent (E-338 guard)", n == 0, f"got {n}")

    print("\n  the message is actionable, and the opt-out works")
    out = run("msg", "nd1 d[3:0] 0 mm\n.model mm busdesc()")
    check("names the offending token", 'd[3:0]' in out and WARN in out)
    check("shows the line it came from", "in line:" in out)
    check("explains the ascending-terminal rule", "ascending bit order" in out)
    check("points at .spiceinit, not .control", ".spiceinit" in out)

    tmp = tempfile.mkdtemp(prefix="busdir_")
    try:
        with open(os.path.join(tmp, ".spiceinit"), "w") as fh:
            fh.write("set nobusdirwarn\n")
        n = run("supp", "nd1 d[3:0] 0 mm\n.model mm busdesc()", cwd=tmp).count(WARN)
        check("`set nobusdirwarn` in .spiceinit silences it", n == 0, f"got {n}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # ...and removing it brings the warning back, so the check above means something
    n = run("unsupp", "nd1 d[3:0] 0 mm\n.model mm busdesc()").count(WARN)
    check("...and without it the warning returns", n == 1, f"got {n}")

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    sys.exit(main())
