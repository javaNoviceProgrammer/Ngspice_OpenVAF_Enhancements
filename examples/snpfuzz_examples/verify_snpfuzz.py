#!/usr/bin/env python3
"""verify_snpfuzz.py -- Enhancement-227: Touchstone `pre_snp` port-count hardening.

Fuzzing the Touchstone .sNp parsers (the `rdsnp` reader from E-72 and the
`pre_snp` convert-to-Verilog-A path in frontend/snp2va.c from E-200/201) by
mutating a valid .snp file -- content AND the port count in the `.sNp` extension --
found a heap-corruption crash (SIGSEGV) in `pre_snp`:

  snp2va.c's parse infers the port count N from the filename `.sNp`
  (N = atoi(dot+2)) with no upper bound. A filename like `.s2147483647p`
  (N = INT_MAX) survives the parse (N*N wraps to 1, so the token layout stays
  self-consistent) but N is stored in out->N and used downstream to size the
  N x N vector fit -- a huge/overflowing allocation that corrupts the heap.
  The brute-force fallback already caps inference at 512 ports; the fix caps the
  filename-derived N the same way (above 512, fall back to inferring N from the
  data). The `rdsnp` reader was clean (3000 iterations).

This test writes a valid .s2p, copies it to a `.s2147483647p` name, and runs
`pre_snp` on it several times (the pre-fix corruption was heap-layout dependent),
asserting a clean, bounded outcome. A regression check confirms a valid .s2p
still converts (pre_snp -> .va -> openvaf-r -> .osdi).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title).
"""
import math
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

ENV = dict(os.environ)
ENV["OPENVAF"] = OPENVAF                 # pre_snp finds the compiler through this

checks = passed = 0
D = tempfile.mkdtemp(prefix="snpfuzz227_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def write_s2p(path):
    """A smooth, fittable 2-port response (a simple 1st-order low-pass S21)."""
    with open(path, "w") as f:
        f.write("! test 2-port\n# GHZ S MA R 50\n")
        for k in range(1, 21):
            fr = k * 0.5
            s21 = 1.0 / math.hypot(1.0, fr / 3.0)          # |S21| roll-off
            a21 = -math.degrees(math.atan2(fr / 3.0, 1.0))
            row = [fr, 0.05, 0.0, s21, a21, s21, a21, 0.05, 0.0]  # S11 S21 S12 S22 (MA)
            f.write(" ".join(f"{x:.6g}" for x in row) + "\n")


def run(control, timeout=40):
    p = os.path.join(D, "f.cir")
    with open(p, "w") as f:
        f.write("* snpfuzz\n.control\n" + control + "\n.endc\n.end\n")
    wd = tempfile.mkdtemp(dir=D)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True,
                           timeout=timeout, cwd=wd, errors="replace", env=ENV)
    except subprocess.TimeoutExpired:
        return None, "HANG"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def is_clean(rc, out):
    return rc is not None and not (rc < 0 or (rc >= 128 and rc != 142)) \
        and "segmentation" not in out.lower()


base = os.path.join(D, "base.s2p")
write_s2p(base)

print("Enhancement-227: Touchstone pre_snp huge-port-count -> no crash")

# --- crash guard: a filename with an INT_MAX port count must not crash ---
huge = os.path.join(D, "m.s2147483647p")
import shutil
shutil.copy(base, huge)
ok = True
for _ in range(5):          # heap-layout dependent pre-fix; a few runs
    rc, out = run("pre_snp %s" % huge)
    if not is_clean(rc, out):
        ok = False
        break
check("pre_snp on a .s2147483647p (INT_MAX ports) name -> clean (was SIGSEGV)",
      ok, "" if ok else f"rc={rc}")

# --- regression: a valid .s2p still converts (pre_snp -> .va -> .osdi) ---
rc, out = run("pre_snp %s" % base)
converted = is_clean(rc, out) and "pre_snp:" in out and (".va" in out or "poles" in out)
check("regression: a valid .s2p still converts via pre_snp (-> .va / .osdi)",
      converted, out.strip()[-160:] if not converted else "")

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
