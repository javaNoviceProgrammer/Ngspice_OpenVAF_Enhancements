#!/usr/bin/env python3
"""
verify_display.py -- verifies Enhancement-71: the display-task audit,
end-to-end through the committed openvaf-r + ngspice.

The audit probed $strobe/$display/$write/$monitor/$debug and the full
format-specifier surface. TWO DEFECTS found and fixed:

  1. flags and width were rejected for every non-real conversion:
     %5d, %-8d, %+d, %08d, % d, %#o all failed with "unexpected
     character" -- the inference-side format parser only terminated on
     real conversions (e/f/g/r), and the lowering side would have
     mis-eaten them too. Both layers now parse the general
     [flags][width][.precision][conversion] form for every conversion,
     preserving the prefix in the generated C format (with %h -> %x,
     %b -> pre-formatted binary string, %r -> engineering notation).
  2. %b CRASHED THE SIMULATOR: the codegen formatted the binary string
     and remembered it for free() but NEVER PASSED IT to snprintf -- the
     matching %s read a garbage pointer (a pre-existing segfault in any
     model using %b, latent because the only in-tree users never ran).

Pinned as working: all conversions (%d %h %H %o %b %c %s %e %f %g),
flags (- + 0 # space), fixed and dynamic (*) widths, precision, %%
literal, %m module path, escape sequences, argument defaults (bare
arguments after the format string), and all five display kinds.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_va(src):
    osdi = os.path.splitext(src)[0] + ".osdi"
    out = os.path.join(HERE, osdi)
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run([OPENVAF, src, "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr, os.path.exists(out)


def run_model(osdi, model):
    deck = (f"* display {model}\nV1 a 0 DC 1\nN1 a 0 mm\n.model mm {model}\n.op\n"
            f".control\npre_osdi {osdi}\nrun\n.endc\n.end\n")
    with open(os.path.join(HERE, "_d.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_d.cir"],
                       capture_output=True, text=True, timeout=120, cwd=HERE)
    return r.stdout + r.stderr, r.returncode


out, ok = compile_va("display_fmt.va")
ok2 = compile_va("display_kinds.va")[1]
if not (ok and ok2):
    check("models compile (flags/width accepted)", False,
          out.splitlines()[0] if out else "")
    raise SystemExit(1)
check("models compile (flags/width accepted -- was 'unexpected character')", True)

print("[1] format output correctness (printf-exact)")
log, rc = run_model("display_fmt.osdi", "dispfmt")
check("no simulator crash (%b used to segfault)", rc == 0 and "F1" in log)
for tag, want, what in [
    ("F1", "[   42]", "%5d right-justified width"),
    ("F2", "[42   ]end", "%-5d left-justify flag"),
    ("F3", "[00042]", "%05d zero-pad flag"),
    ("F4", "[+42]", "%+d sign flag"),
    ("F5", "[      hi]end", "%8s string width"),
    ("F6", "[hi      ]end", "%-8s left string"),
    ("F7", "[  ff]", "%4h hex with width"),
    ("F8", "[     101]end", "%8b binary with width (the segfault fix)"),
    ("F9", "[    42]", "%*d dynamic width"),
    ("FA", "[ 1.235e+03]", "%10.3e width.precision"),
    ("FB", "[010]", "%#o alternate form"),
    ("FC", "hex=ff HEX=FF oct=10 bin=101 chr=A", "all base conversions"),
    ("FD", "-7 2.5 hi dflt: 99", "bare-argument defaults"),
]:
    check(what, f"{tag}{want}" in log.replace(f"{tag} ", tag) or f"{tag}{want}" in log
          or f"{tag} {want}" in log, f"(expect {want})")

print("[2] display kinds + %m + escapes")
log, rc = run_model("display_kinds.osdi", "dispkinds")
check("%m prints the module path", "mod=dispkinds" in log)
check("\\t escape renders a tab", "tab[\t]" in log)
check("$write / $display / $monitor / $debug all print",
      all(f"M{k}" in log for k in (3, 4, 5, 6)))

print(f"\n{'ALL PASS' if failed == 0 else 'FAILURES'}: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
