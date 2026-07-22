#!/usr/bin/env python3
"""verify_letidxoob.py -- Enhancement-280: an out-of-range SINGLE index in an
indexed `let` assignment no longer writes past the end of the vector.

`get_index_values` (src/frontend/com_let.c) parses either one index (`v[i]`) or a
range (`v[lo:hi]`). It validated `low > high` and `high >= n_elem_this_dim` -- but
those checks lived **inside the range branch only**. A single index returned
completely unchecked, so

    let vx[100] = 1        # on a 66-element vector

walked straight into the byte-offset arithmetic and performed a
**heap-buffer-overflow WRITE** (AddressSanitizer: `WRITE of size ...`). That is
memory corruption from an ordinary typo, not an exotic input. The range form
`vx[0:999]` was correctly rejected all along.

Fixed by moving both checks after the if/else so they validate a single index too.
Reads are unaffected (`op_ind` clamps an out-of-range read index, Enhancement-274).

Passes iff out-of-range assignments are rejected cleanly and valid ones still assign.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = "* let index bounds test\nr1 a 0 1k\nv1 a 0 dc 1\n"
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=15):
    deck = BASE + ".control\nlet w = vector(10)\n" + control + "\nquit\n.endc\n.end\n"
    path = os.path.join(HERE, "_lx.cir")
    with open(path, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


def nocrash(rc):
    return rc is not None and rc >= 0 and rc != 139


print("Enhancement-280: out-of-range `let v[i] = x` -> clean error (was an OOB WRITE)")

# [1] the headline case: a plain out-of-range single index (w has 10 elements).
rc, out = run("let w[10] = 99")
check("[1] `let w[10] = 99` on a 10-element vector -> clean error (was OOB WRITE)",
      nocrash(rc) and "exceeds" in out.lower() and "Sanitizer" not in out, f"rc={rc}")

# [2] a far out-of-range index.
rc, out = run("let w[999] = 99")
check("[2] `let w[999] = 99` -> clean error", nocrash(rc) and "exceeds" in out.lower(),
      f"rc={rc}")

# [3] a non-representable index (also exercises the Enhancement-279 cast clamp).
rc, out = run("let w[1e308] = 99")
check("[3] `let w[1e308] = 99` -> clean error, no UB", nocrash(rc)
      and "outside the range" not in out.lower(), f"rc={rc}")

# [4] the LAST valid index still assigns.
rc, out = run("let w[9] = 42\nprint w[9]")
m = re.search(r"w\[9\]\s*=\s*([-\d.eE+]+)", out)
check("[4] the last valid index `let w[9] = 42` still assigns", nocrash(rc)
      and m is not None and abs(float(m.group(1)) - 42.0) < 1e-9,
      f"={m.group(1) if m else '?'}")

# [5] a mid-vector assignment still works.
rc, out = run("let w[4] = 7\nprint w[4]")
m = re.search(r"w\[4\]\s*=\s*([-\d.eE+]+)", out)
check("[5] a valid `let w[4] = 7` still assigns", nocrash(rc)
      and m is not None and abs(float(m.group(1)) - 7.0) < 1e-9,
      f"={m.group(1) if m else '?'}")

# [6] the range form is still rejected when out of range (unchanged behaviour).
rc, out = run("let w[0:999] = 1")
check("[6] the range form `w[0:999]` is still rejected", nocrash(rc)
      and "exceeds" in out.lower(), f"rc={rc}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
