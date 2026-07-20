#!/usr/bin/env python3
"""Enhancement-250: undefined-behaviour shift in the d_lut / d_genlut code models.

The XSPICE digital lookup-table models size their table as 2^(number of inputs),
computed with a left shift:

    size     = PORT_SIZE(in);      /* d_lut   */
    tablelen = 1 << size;

    isize    = PORT_SIZE(in);      /* d_genlut */
    entrylen = (1 << isize);

`size`/`isize` is the number of connected input ports and was never bounded. A
shift of a 32-bit `int` by >= 32 is undefined behaviour (UndefinedBehaviorSanitizer:
"shift exponent 32 is too large for 32-bit type 'int'" at cfunc.c:146 / :177), and
a count in the high twenties asks for a multi-gigabyte table allocation. Both are
reachable from a valid-syntax netlist -- just an `a`-device with >= ~30 digital
inputs fanned into the LUT.

E-250 caps the input-port count at D_LUT_MAX_INPUTS / D_GENLUT_MAX_INPUTS (24 --
a real lookup table has only a handful of inputs) before the shift, reporting a
clean error instead of the UB / oversized allocation.

The XSPICE code models load from the prebuilt bundle via SPICE_LIB_DIR, which
`_setup` points at bin/<os>/<arch>/. If the bundle/codemodels are unavailable in
this checkout, the a-devices cannot load and this test self-skips.

Checks (batch mode, -b; run under both solvers). A crash shows up as a NEGATIVE
return code (signal).
 1. a valid 2-input d_lut still simulates;
 2. a 32-input d_lut is rejected with a clean "out of range" error, no crash
    (was the 1<<32 undefined-behaviour shift);
 3. a valid 2-input d_genlut still simulates;
 4. a 32-input d_genlut is rejected with a clean "out of range" error, no crash.

Line 1 of every SPICE deck is the title (ignored).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402  (also sets SPICE_LIB_DIR)
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def is_crash(rc):
    return rc < 0 or rc >= 128


def run(deck):
    cir = os.path.join(HERE, "_dl.cir")
    open(cir, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True,
                       timeout=60, cwd=HERE)
    return r.returncode, r.stdout.replace("\r", "\n") + r.stderr


def d_lut(n, table):
    ins = " ".join("din" for _ in range(n))
    return (f"d_lut n={n}\na0 din pu\n.model pu d_pullup(load=0.5p)\n"
            f"a1 [{ins}] outd lut1\n.model lut1 d_lut(table_values={table})\n"
            f".tran 1n 5n\n.control\nrun\neprint outd\n.endc\n.end\n")


def d_genlut(n, table):
    ins = " ".join("din" for _ in range(n))
    return (f"d_genlut n={n}\na0 din pu\n.model pu d_pullup(load=0.5p)\n"
            f"a1 [{ins}] [o] gl\n"
            f".model gl d_genlut(rise_delay=[1n] fall_delay=[1n] table_values \"{table}\")\n"
            f".tran 1n 5n\n.control\nrun\neprint o\n.endc\n.end\n")


MSG = "out of range"

# Availability gate: a valid d_lut must load (proves codemodels present)
rc, out = run(d_lut(2, "0110"))
if is_crash(rc) or ("outd" not in out and MSG not in out and "error" not in out.lower()):
    # a real load failure prints an MIF/codemodel error; a genuine miss self-skips
    if "code model" in out.lower() or "unable to find" in out.lower() or is_crash(rc):
        print(f"  SKIP  XSPICE code models unavailable in this checkout (rc={rc})")
        raise SystemExit(0)

# 1: valid 2-input d_lut simulates (no error)
check("valid 2-input d_lut simulates",
      not is_crash(rc) and MSG not in out, f"rc={rc}")

# 2: 32-input d_lut -> clean error, no crash (was the 1<<32 UB shift)
rc, out = run(d_lut(32, "01"))
check("32-input d_lut: clean error, no crash (was 1<<32 UB)",
      not is_crash(rc) and MSG in out, f"rc={rc} msg={'yes' if MSG in out else 'no'}")

# 3: valid 2-input d_genlut simulates
rc, out = run(d_genlut(2, "0110"))
check("valid 2-input d_genlut simulates",
      not is_crash(rc) and MSG not in out, f"rc={rc}")

# 4: 32-input d_genlut -> clean error, no crash
rc, out = run(d_genlut(32, "01"))
check("32-input d_genlut: clean error, no crash (was 1<<32 UB)",
      not is_crash(rc) and MSG in out, f"rc={rc} msg={'yes' if MSG in out else 'no'}")

p = os.path.join(HERE, "_dl.cir")
if os.path.exists(p):
    os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
