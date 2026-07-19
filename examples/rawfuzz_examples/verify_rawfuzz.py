#!/usr/bin/env python3
"""verify_rawfuzz.py -- Enhancement-226: ngspice rawfile-load crash hardening.

Fuzzing the nutmeg rawfile reader (`raw_read` in frontend/rawfile.c, reached by
the `load` command) by mutating a valid `.raw` file found a NULL-dereference
crash (SIGSEGV, memmove into 0x0):

  raw_read resets flags = VF_PERMANENT per plot and sets VF_REAL / VF_COMPLEX
  only from a `Flags:` line; each vector is then allocated with dvec_alloc(...,
  flags, npoints, ...), which allocates v_realdata OR v_compdata from those bits.
  A rawfile with NO valid Flags: line -- missing, or only unknown flags like
  "Flags: xyz" -- leaves flags without VF_REAL/VF_COMPLEX, so NO data array is
  allocated, and the value-reading loop dereferences the NULL buffer. Fixed by
  defaulting to real (with a warning) when the type is absent.

This test writes a valid .raw with `write`, crafts the pathological variants, and
`load`s each -- asserting a clean, bounded outcome (no signal/abort). A regression
check confirms a valid .raw still round-trips write -> load with the right length.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

checks = passed = 0
D = tempfile.mkdtemp(prefix="rawfuzz226_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def run(control, timeout=25):
    """Run a .control block over an empty circuit; return (rc, output)."""
    p = os.path.join(D, "f.cir")
    with open(p, "w") as f:
        f.write("* rawfuzz\n.control\n" + control + "\n.endc\n.end\n")
    wd = tempfile.mkdtemp(dir=D)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True,
                           timeout=timeout, cwd=wd, errors="replace")
    except subprocess.TimeoutExpired:
        return None, "HANG"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def is_clean(rc, out):
    return rc is not None and not (rc < 0 or (rc >= 128 and rc != 142)) \
        and "segmentation" not in out.lower()


# --- write a valid .raw (ascii) to mutate ---
base = os.path.join(D, "base.raw")
gen = ("* gen\nV1 1 0 sin(0 1 1k)\nR1 1 2 1k\nC1 2 0 1u\n.tran 20u 200u\n.control\n"
       "run\nset filetype=ascii\nwrite %s v(1) v(2)\n.endc\n.end\n" % base)
with open(os.path.join(D, "gen.cir"), "w") as f:
    f.write(gen)
subprocess.run([NGSPICE, "-b", os.path.join(D, "gen.cir")],
               capture_output=True, text=True, cwd=D)
raw = open(base, "rb").read() if os.path.exists(base) else b""

print("Enhancement-226: malformed rawfile load -> clean (no crash)")
check("wrote a valid base .raw to mutate", raw.startswith(b"Title:") and b"Flags:" in raw,
      f"{len(raw)} bytes")

# --- pathological variants: each must LOAD cleanly (no crash) ---
noflags  = re.sub(rb"Flags:[^\n]*\n", b"", raw, count=1)           # Flags line removed
badflags = re.sub(rb"Flags:[^\n]*",  b"Flags: xyz", raw, count=1)  # unknown flag only
for name, data in (("Flags: line removed", noflags),
                   ("Flags: xyz (unknown flag only)", badflags)):
    rf = os.path.join(D, "m.raw")
    open(rf, "wb").write(data)
    rc, out = run("load %s\nprint length(v(1))" % rf)
    check(f"load a rawfile with {name} -> clean (was SIGSEGV)", is_clean(rc, out), f"rc={rc}")

# --- regression: a valid .raw still round-trips ---
rc, out = run("load %s\nprint length(v(1))" % base)
m = re.search(r"length\(v\(1\)\)\s*=\s*([-\d.eE+]+)", out)
n = float(m.group(1)) if m else None
check("regression: a valid .raw still loads (write -> load, length 62)",
      is_clean(rc, out) and n is not None and abs(n - 62) < 0.5, f"len={n}")

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
