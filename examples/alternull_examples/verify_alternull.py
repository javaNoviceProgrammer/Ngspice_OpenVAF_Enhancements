#!/usr/bin/env python3
"""verify_alternull.py -- Enhancement-272: `alter <dev> = <value>` (and the `sweep`
knob path) no longer dereferences a NULL parameter for an m-named device.

`com_alter_common` (src/frontend/device.c) supports altering a device's *principal*
value with no named parameter -- `alter r1 = 2k` -- in which case `param` is NULL.
Just before applying the value it runs a binned-MOS guard:

    if ((dev[0] == 'm') && (eq(param, "w") || eq(param, "l"))) ...

`eq` is `!strcmp(...)`, so when the device name starts with `m` and `param` is NULL
(`alter mfoo = 5`, or the same call synthesized by the `sweep` command for a knob
with no bracketed parameter), `strcmp(NULL, "w")` dereferences NULL and the process
SEGV-crashes -- on the shipped build, not just under ASan. Fixed by testing `param`
first (`param && (dev[0] == 'm') && ...`); a NULL param simply skips the bin check,
which needs a `w`/`l` parameter anyway.

The test passes iff the NULL-param inputs error cleanly (no crash) and valid alters
still work. Reported via exit code (0 = pass).
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = "* alter null-param test\nr1 a b 1k\nr2 b 0 1k\nv1 a 0 1\n"
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=15):
    deck = BASE + ".control\n" + control + "\nquit\n.endc\n.end\n"
    path = os.path.join(HERE, "_an.cir")
    with open(path, "w") as f:
        f.write(deck)
    t0 = time.time()
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or ""), time.time() - t0
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]", time.time() - t0


# A SEGV shows up as a negative return code (signal) / 139; a clean run is >= 0.
def nocrash(rc):
    return rc is not None and rc >= 0 and rc != 139


print("Enhancement-272: alter/sweep no longer deref a NULL param for m-named devices")

# [1] direct `alter mfoo = 5`: m-named device, NULL param -> was a SEGV.
rc, out, dt = run("alter mfoo = 5")
check("[1] `alter mfoo = 5` (m-device, NULL param) -> clean error, no crash (was SEGV)",
      nocrash(rc) and "no such device" in out.lower(), f"rc={rc}")

# [2] the fuzz-found sweep knob path that synthesized the same NULL-param call.
rc, out, dt = run("sweep mag(v(b)) 0 1k 5k 1k")
check("[2] `sweep mag(v(b)) 0 1k 5k 1k` -> no crash (was SEGV via sw_run_cmd)",
      nocrash(rc) and dt < 10, f"rc={rc} {dt:.1f}s")

# [3] a valid principal-value alter (param IS NULL) still works: r1 1k->2k.
rc, out, dt = run("op\nprint i(v1)\nalter r1 = 2k\nop\nprint i(v1)")
# i(v1) = -1/(r1+r2): 1k+1k -> -5e-4 ; 2k+1k -> -3.333e-4
ok3 = nocrash(rc) and "-5.00000e-04" in out and "-3.33333e-04" in out
check("[3] valid NULL-param `alter r1 = 2k` still changes the value (-5e-4 -> -3.33e-4)",
      ok3, f"rc={rc}")

# [4] the param-non-NULL m-device binning branch stays crash-safe.
rc, out, dt = run("alter mfoo w=2u")
check("[4] `alter mfoo w=2u` (m-device, non-NULL param) -> clean error, no crash",
      nocrash(rc) and "no such device" in out.lower(), f"rc={rc}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
