#!/usr/bin/env python3
"""Enhancement-238: fix a NULL-deref crash on a malformed differential token.

`gettoks()` (frontend/dotcards.c) parses the output tokens of `.save`/`.print`/
`.plot`/`.four` (and `.measure` vars). For a differential form like `v(a,b)` it
finds the comma `c` and the close paren `r` and splits the second operand off at
`r`:

    r = strchr(t, ')');
    c = strchr(t, ',');
    ...
    if (c != r) {          /* a comma distinct from the ')' -> differential */
        *r = '\\0';         /* <-- r is NULL for a malformed "v(1," */
        ...
    }

A MALFORMED token such as `v(1,` has a comma but NO ')', so `r` is NULL while
`c` is not; `c != r` is then true and `*r = '\\0'` dereferences NULL -> SIGSEGV.
It is reachable from `.save`/`.print`/`.plot`/`.four`/`.measure`. E-238 guards the
split with `if (r && c != r)`, so a malformed token degrades to a harmless parse
instead of crashing.

Checks (batch mode, `-b`). A crash shows up as a NEGATIVE return code (signal);
a clean run is 0 (or 1 for a benign parse/"no such vector" error).
 1. `.print tran v(1,` no longer crashes (was SIGSEGV);
 2. the same malformed token across `.save`/`.plot`/`.four`/`.measure` and other
    prefixes (`i(1,`, `vdb(1,`) no longer crashes;
 3. a well-formed differential `v(1,2)` still rewrites to v(1)-v(2) and computes
    the correct value.

Line 1 of every SPICE deck is the title (ignored).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


BASE = "v1 1 0 dc 3\nr1 1 2 1k\nr2 2 0 1k\n"


def run(card_line, analysis=".tran 1u 1m"):
    deck = f"* malformed-token test\n{BASE}{analysis}\n{card_line}\n.end\n"
    cir = os.path.join(HERE, "_mf.cir")
    open(cir, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True,
                       timeout=60)
    return r.returncode, r.stdout.replace("\r", "\n") + r.stderr


# 1: the exact repro
rc, _ = run(".print tran v(1,")
check("`.print tran v(1,` no longer crashes (was SIGSEGV / NULL deref)",
      rc >= 0, f"rc={rc}")

# 2: the same malformed shape across cards and prefixes
cases = [
    (".save v(1,", ".tran 1u 1m"),
    (".plot tran v(1,", ".tran 1u 1m"),
    (".four 1k v(1,", ".tran 1u 1m"),
    (".meas tran m1 MAX v(1,", ".tran 1u 1m"),
    (".print tran i(1,", ".tran 1u 1m"),
    (".print tran vdb(1,", ".tran 1u 1m"),
    (".print ac vm(1,", ".ac dec 10 1 1k"),
]
worst = max((run(c, a)[0] for c, a in cases), key=lambda rc: -rc if rc < 0 else -100)
allok = all(run(c, a)[0] >= 0 for c, a in cases)
check("malformed token across .save/.plot/.four/.meas + i()/vdb()/vm() no crash",
      allok, "all clean" if allok else "a case still crashes")

# 3: well-formed differential still correct (v(1)-v(2) = 3*(1k/2k) = 1.5)
rc, out = run(".print tran v(1,2)")
m = re.search(r"^0[ \t]+[-\d.eE+]+[ \t]+([-\d.eE+]+)", out, re.M)
val = float(m.group(1)) if m else None
check("well-formed v(1,2) still rewrites to v(1)-v(2)=1.5 correctly",
      rc == 0 and val is not None and abs(val - 1.5) < 1e-6,
      f"rc={rc} diff={val}")

p = os.path.join(HERE, "_mf.cir")
if os.path.exists(p):
    os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
