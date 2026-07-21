#!/usr/bin/env python3
"""verify_letoob.py -- Enhancement-271: the `let` command no longer reads one byte
before its buffer on an empty or all-whitespace left-hand side.

`com_let` flattens its arguments into a heap string `p`, splits off the RHS at `=`,
then NUL-terminates the vector name at the first `[`. When the LHS is a bare `[`
(so `p` becomes ""), or is entirely whitespace, the trailing-space trim

    for (q = p + strlen(p) - 1; *q <= ' ' && p <= q; q--) ...

started with `q = p - 1` and dereferenced `*q` *before* the `p <= q` guard could
short-circuit -- a one-byte read before the allocation, caught by AddressSanitizer
(heap-buffer-overflow READ at com_let.c) on `let [[ = ...`. Fixed by testing the
bound first (`p <= q && *q <= ' '`); the empty name then falls through to the
existing "bad variable name" check.

The shipped build does not fault deterministically on that stray read, so this test
verifies the observable contract instead: a malformed `let` LHS errors cleanly and
quickly (no hang, no crash), and valid `let` assignments are unaffected. Reported
via exit code (0 = pass).
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = "* let-oob test\nr1 a 0 1k\nv1 a 0 1\n"
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=15):
    deck = BASE + ".control\n" + control + "\nquit\n.endc\n.end\n"
    path = os.path.join(HERE, "_let.cir")
    with open(path, "w") as f:
        f.write(deck)
    t0 = time.time()
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or ""), time.time() - t0
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]", time.time() - t0


print("Enhancement-271: `let` empty/whitespace LHS -> clean error (was a 1-byte OOB read)")

# [1] the exact fuzz-found input: a bare-bracket LHS -> was a heap OOB read.
rc, out, dt = run("let [[ = v(a)")
check("[1] `let [[ = ...` -> clean 'bad variable name', no crash/hang (was OOB read)",
      rc == 0 and "bad variable name" in out.lower() and dt < 10, f"rc={rc} {dt:.1f}s")

# [2] a single leading bracket -> empty vector name, same path.
rc, out, dt = run("let [ = 5")
check("[2] `let [ = 5` -> clean 'bad variable name', no crash", rc == 0 and dt < 10,
      f"rc={rc} {dt:.1f}s")

# [3] an all-whitespace LHS also drove q below p before the fix.
rc, out, dt = run("let    = 5")
check("[3] all-whitespace LHS -> clean error, no crash", rc == 0 and dt < 10,
      f"rc={rc} {dt:.1f}s")

# [4] a plain `let` assignment still works.
rc, out, dt = run("let a = 5\nprint a")
check("[4] a valid `let a = 5` still assigns 5", rc == 0 and "5.00000" in out,
      f"rc={rc}")

# [5] an indexed `let` into an existing vector still works.
rc, out, dt = run("let a = vector(3)\nlet a[1] = 7\nprint a[1]")
check("[5] a valid indexed `let a[1] = 7` still works", rc == 0 and "7.00000" in out,
      f"rc={rc}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
