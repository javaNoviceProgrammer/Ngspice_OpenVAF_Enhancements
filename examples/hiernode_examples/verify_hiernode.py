#!/usr/bin/env python3
"""Enhancement-428: reach a device's internal node by the name you'd write.

A Verilog-A device declares an internal node `mid`. ngspice names it after the
flattened instance, so at the top level it is `n1#mid` -- and that always
worked:

    print v(n1#mid)          ->  7.50000000e-01

Put the same device inside a subcircuit and the name grows a device TYPE LETTER,
because subcircuit expansion re-parses the emitted card and dispatches on its
first character (Enhancement-410 documents this at length). The vector becomes
`n.x1.n1#mid`, and the obvious spelling did not resolve:

    print v(n.x1.n1#mid)     ->  7.50000000e-01
    print v(x1.n1#mid)       ->  Warning ... not available or has zero length

That letter is a flattening artefact, and a NODE name is the one place a user
never expects it -- the plain node beside it is `x1.m`, with no letter at all.
This release accepts the obvious spelling everywhere a node vector is consumed.

WHY THE RECONSTRUCTION IS SAFE. It needs no search and cannot be ambiguous: the
letter prepended is literally the leaf instance name's own first character, and
ngspice requires a device's name to begin with its type letter -- so `x1.n1` can
only ever mean `n.x1.n1`. It is STRICTLY a fallback, consulted only after the
exact lookups have failed, so every name that resolves today resolves to exactly
what it did before.

TWO INDEPENDENT RESOLUTION PATHS. `print`/`let`/`meas`/`wrdata` go through
`findvec` (vectors.c); `.save` matches on its own comparator in outitf.c. Only
fixing the first would have left `.save v(x1.n1#mid)` silently matching nothing
-- and its failure is destructive, ending the run with "no data saved for
Transient analysis; analysis not run", losing the whole plot rather than one
vector. That split is the Enhancement-408 lesson, and it is why both paths are
exercised below.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    if ok:
        passed += 1
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")


def build():
    r = subprocess.run([OPENVAF, os.path.join(HERE, "hiernode.va"),
                        "-o", os.path.join(HERE, "hiernode.osdi")],
                       capture_output=True, text=True, cwd=HERE, timeout=300)
    if r.returncode:
        print(r.stdout + r.stderr)
    return r.returncode == 0


def run(deck, name="_hn.cir", timeout=120):
    path = os.path.join(HERE, name)
    with open(path, "w") as fh:
        fh.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -99, "TIMEOUT"


def scalar(out, name):
    """ngspice lowercases vector names on output, so match case-insensitively."""
    m = re.search(r"^%s\s*=\s*(\S+)" % re.escape(name), out, re.M | re.I)
    return float(m.group(1)) if m else None


def close(a, b, tol=1e-6):
    return isinstance(a, float) and abs(a - b) <= tol * max(1.0, abs(b))


LOAD = ".control\npre_osdi hiernode.osdi\n.endc\n"     # for pure-card decks
SUB = ("V1 a 0 dc 1\n.subckt blk p q\nN1 p m hm\nRx m q 1u\n.ends\n"
       "X1 a 0 blk\n.model hm hiernode()\n")   # `m` is a real internal node
FLAT = "V1 a 0 dc 1\nN1 a 0 hm\n.model hm hiernode()\n"
DEEP = ("V1 a 0 dc 1\n.subckt inner p q\nN1 p q hm\n.ends\n"
        ".subckt blk p q\nX2 p q inner\n.ends\nX1 a 0 blk\n.model hm hiernode()\n")

WANT = 0.75           # 3k / (1k + 3k), with v(a) = 1


def ctl(body):
    return (".control\npre_osdi hiernode.osdi\noption noacct\nset numdgt=8\n"
            + body + "\n.endc\n.end\n")


def main():
    if not build():
        print("FATAL: hiernode.va did not compile")
        sys.exit(1)

    print("\n[1] the name that always worked keeps working")
    rc, out = run("* hn\n" + FLAT + ctl("op\nprint v(n1#mid)"))
    check("top level: v(n1#mid)", close(scalar(out, "v(n1#mid)"), WANT),
          str(scalar(out, "v(n1#mid)")))
    rc, out = run("* hn\n" + SUB + ctl("op\nprint v(n.x1.n1#mid)"))
    check("in a subcircuit, device-letter form: v(n.x1.n1#mid)",
          close(scalar(out, "v(n.x1.n1#mid)"), WANT),
          str(scalar(out, "v(n.x1.n1#mid)")))

    print("\n[2] the obvious spelling now resolves, in every consumer")
    rc, out = run("* hn\n" + SUB + ctl("op\nprint v(x1.n1#mid)"))
    check("print v(x1.n1#mid)", close(scalar(out, "v(x1.n1#mid)"), WANT),
          str(scalar(out, "v(x1.n1#mid)")))
    rc, out = run("* hn\n" + SUB + ctl("op\nlet q = v(x1.n1#mid)\nprint q"))
    check("let q = v(x1.n1#mid)", close(scalar(out, "q"), WANT), str(scalar(out, "q")))
    rc, out = run("* hn\n" + SUB + ctl("op\nlet q = v(x1.n1#mid)*2\nprint q"))
    check("...and inside an expression", close(scalar(out, "q"), 2 * WANT))
    rc, out = run("* hn\n" + SUB + ctl("op\nprint v(X1.N1#MID)"))
    check("the name is case-insensitive, as node names are",
          close(scalar(out, "v(x1.n1#mid)"), WANT))
    rc, out = run("* hn\n" + SUB
                  + ctl("tran 1u 6u\nlet L = length(v(x1.n1#mid))\nprint L"))
    check("length() over a transient", (scalar(out, "L") or 0) > 1, str(scalar(out, "L")))
    rc, out = run("* hn\n" + SUB
                  + ctl("tran 1u 6u\nmeas tran q MAX v(x1.n1#mid)"))
    check("meas tran MAX", "7.50000e-01" in out, out[-120:].replace("\n", " "))
    rc, out = run("* hn\n" + SUB
                  + ctl("tran 1u 6u\nwrdata _hn.txt v(x1.n1#mid)"))
    p = os.path.join(HERE, "_hn.txt")
    n = sum(1 for _ in open(p)) if os.path.exists(p) else 0
    check("wrdata writes a real waveform", n > 1, f"{n} rows")

    print("\n[3] the .save path resolves it too (a separate comparator)")
    rc, out = run("* hn\n" + SUB
                  + ctl("save v(x1.n1#mid)\ntran 1u 6u\ndisplay"))
    check("save v(x1.n1#mid) -> the vector exists",
          "n.x1.n1#mid" in out and "no data saved" not in out,
          out[-140:].replace("\n", " "))
    rc, out = run("* hn\n" + SUB + LOAD
                  + ".save v(x1.n1#mid)\n.dc v1 1 1 1\n.print dc v(x1.n1#mid)\n.end\n")
    check(".save + .print as netlist CARDS", "7.500000e-01" in out,
          out[-140:].replace("\n", " "))
    rc, out = run("* hn\n" + SUB
                  + ctl("save v(x1.n1#mid)\ntran 1u 6u\nwrite _hn.raw v(x1.n1#mid)\n"
                        "destroy all\nload _hn.raw\nlet L = length(v(x1.n1#mid))\nprint L"))
    check("write + reload round-trips a real waveform",
          (scalar(out, "L") or 0) > 1, f"reloaded length = {scalar(out, 'L')}")

    print("\n[4] deeper nesting")
    rc, out = run("* hn\n" + DEEP + ctl("op\nprint v(x1.x2.n1#mid)"))
    check("v(x1.x2.n1#mid) at two levels", close(scalar(out, "v(x1.x2.n1#mid)"), WANT),
          str(scalar(out, "v(x1.x2.n1#mid)")))

    print("\n[5] nothing else moves")
    rc, out = run("* hn\n" + SUB + ctl("op\nprint v(x1.nosuch#mid)"))
    check("a bad leaf name still fails", "not available" in out)
    rc, out = run("* hn\n" + SUB + ctl("op\nprint v(nosuch#mid)"))
    check("a non-hierarchical bad name still fails", "not available" in out)
    rc, out = run("* hn\n" + SUB + ctl("op\nprint v(a)"))
    check("an ordinary node is untouched", close(scalar(out, "v(a)"), 1.0))
    rc, out = run("* hn\n" + SUB + ctl("op\nprint v(x1.m)"))
    check("an ordinary HIERARCHICAL node is untouched (no letter, as always)",
          close(scalar(out, "v(x1.m)"), 0.0, 1e-3), str(scalar(out, "v(x1.m)")))

    for j in os.listdir(HERE):
        if j.startswith("_hn") or j.endswith(".osdi"):
            p = os.path.join(HERE, j)
            (shutil.rmtree if os.path.isdir(p) else os.remove)(p)

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
