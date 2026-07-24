#!/usr/bin/env python3
"""verify_sffmoffset.py -- Enhancement-318: VSRC SFFM/AM sources dropped the DC offset VO
before the delay (returned 0 for time<=TD), unlike SIN.

Found by oracle-checking transient waveform sources against the closed-form definition and,
decisively, against the SAME quantity computed two other ways: SIN in the same binary holds its
quiescent value at time<=0, and ngspice's OWN current-source SFFM (isrcload.c) has no such
zeroing. vsrcload.c had `if (time <= 0) value = 0;` for SFFM (and AM); the fix holds the
waveform's time=0 value there, matching SIN and the current-source implementation.

Over the pre-delay window a 0.2ms-delayed SFFM(VO=1.5,...) must read 1.5 and AM(VO=2,...) must
read 2.0, exactly as the SIN control reads 1.5. Both fail on the pre-fix binary (they read 0).
"""
import os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
passed = failed = 0
def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    passed += ok; failed += (not ok)
r = subprocess.run([NGSPICE, "-b", "sffm_offset.sp"], cwd=HERE, capture_output=True, text=True, timeout=60)
out = (r.stdout or "") + (r.stderr or "")
def m(name):
    g = re.search(name + r"\s*=\s*([-\d.eE+]+)", out)
    return float(g.group(1)) if g else None
print("Enhancement-318: SFFM/AM hold the DC offset before the delay")
check("SFFM holds VO=1.5 in the pre-delay window (was 0)", m("m_sffm") is not None and abs(m("m_sffm")-1.5)<1e-6, f"={m('m_sffm')}")
check("AM holds VO=2.0 in the pre-delay window (was 0)", m("m_am") is not None and abs(m("m_am")-2.0)<1e-6, f"={m('m_am')}")
check("SIN control still holds 1.5 (unchanged)", m("m_sin") is not None and abs(m("m_sin")-1.5)<1e-6, f"={m('m_sin')}")
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
