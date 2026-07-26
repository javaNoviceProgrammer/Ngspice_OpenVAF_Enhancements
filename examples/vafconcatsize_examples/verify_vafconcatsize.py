#!/usr/bin/env python3
"""Enhancement-325: bound the MATERIALIZED size of `{...}` / `{n{...}}`.

Enhancement-314 capped the replication COUNT at 2^20. The count is only one factor
of the final size, so two abusive shapes still got through and hit the SHIPPED
compiler:

  * `parameter string s = {200000{"x"}};`
      a string concatenation lowers to a generated LLVM callback with ONE PARAMETER
      PER OPERAND, and LLVM degrades super-linearly in arity (2000 -> 0.4 s,
      8000 -> 2.9 s, 16000 -> 8.6 s, 32000 -> never finished). This HUNG the
      compiler on one line of source.

  * `real c[0:1]; c = {1048576{{1048576{1.0}}}};`
      both counts are individually legal (= 2^20) but the product is 2^40, which
      overflowed the u32 array length: a panic under overflow-checks, and in the
      shipped release a silent WRAP to 0 that produced the nonsense diagnostic
      "expected real[0:2] value but found real[0:0] value".

The size is now computed in u64 with saturating arithmetic and bounded before it is
narrowed, with a dedicated diagnostic. Checks 1-3 FAIL on the pre-fix binary (hang
or wrong/absent diagnostic); check 4 is the forward guard that legitimate
concatenation still compiles and simulates.
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


DISC = '`include "disciplines.vams"\n'


def compile_src(src, name, timeout=25):
    """Compile a snippet. Returns (returncode|'HANG', combined output, seconds)."""
    path = os.path.join(HERE, name + ".va")
    with open(path, "w") as f:
        f.write(src)
    t0 = time.time()
    try:
        r = subprocess.run([OPENVAF, path, "-o", os.path.join(HERE, name + ".osdi")],
                           capture_output=True, text=True, timeout=timeout)
        rc, out = r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        rc, out = "HANG", ""
    finally:
        for p in (path, os.path.join(HERE, name + ".osdi")):
            if os.path.exists(p):
                os.remove(p)
    return rc, out, time.time() - t0


def main():
    # [1] string replication that would become a 200000-parameter LLVM callback
    rc, out, dt = compile_src(
        DISC + 'module _s(a); inout a; electrical a;\n'
               '  parameter string s = {200000{"x"}};\n'
               'endmodule\n', "_s")
    ok = rc != "HANG" and "too many elements" in out
    check("huge string replication is rejected, not hung", ok,
          f"rc={rc} in {dt:.1f}s")

    # [2] nested replication whose product (2^40) overflowed the u32 length
    rc, out, dt = compile_src(
        DISC + 'module _n(a,b); inout a,b; electrical a,b;\n'
               '  real c[0:1];\n'
               '  analog c = {1048576{{1048576{1.0}}}};\n'
               'endmodule\n', "_n")
    ok = rc != "HANG" and "too many elements" in out
    check("2^40 nested replication is rejected with a real diagnostic", ok,
          f"rc={rc}")
    # the reported size must be the true u64 product, not a wrapped value
    m = re.search(r"expand to (\d+) elements", out)
    check("the diagnostic reports the true expanded size (2^40)",
          bool(m) and int(m.group(1)) == 1 << 40,
          m.group(1) if m else "no size in message")

    # [3] exactly 2^32 -- the value that wrapped to zero in release
    rc, out, _ = compile_src(
        DISC + 'module _w(a,b); inout a,b; electrical a,b;\n'
               '  real c[0:1];\n'
               '  analog c = {65536{{65536{1.0}}}};\n'
               'endmodule\n', "_w")
    check("2^32 replication (the wrap-to-zero case) is rejected",
          rc != "HANG" and "too many elements" in out, f"rc={rc}")

    # [4] forward guard: legitimate concatenation still compiles AND simulates
    osdi = os.path.join(HERE, "concat_ok.osdi")
    if os.path.exists(osdi):
        os.remove(osdi)
    r = subprocess.run([OPENVAF, os.path.join(HERE, "concat_ok.va"), "-o", osdi],
                       capture_output=True, text=True, timeout=120)
    check("legitimate concatenation/replication still compiles", r.returncode == 0,
          f"rc={r.returncode}")
    if r.returncode == 0:
        deck = os.path.join(HERE, "_ok.cir")
        with open(deck, "w") as f:
            f.write("concat ok\nV1 n1 0 dc 1\nN1 n1 0 cmod\n.model cmod concat_ok\n"
                    ".control\npre_osdi concat_ok.osdi\nop\nprint i(v1)\n.endc\n.end\n")
        try:
            rr = subprocess.run([NGSPICE, "-b", os.path.basename(deck)], cwd=HERE,
                                capture_output=True, text=True, timeout=120)
            out = rr.stdout + rr.stderr
        finally:
            if os.path.exists(deck):
                os.remove(deck)
        m = re.search(r"i\(v1\)\s*=\s*([-\d.eE+]+)", out)
        # g[0] = 2.0 from {6{2.0}}, so I = V * 2.0 * 1e-3 = 2 mA (source current is -I)
        got = float(m.group(1)) if m else None
        check("and simulates: the replicated value is used (i(v1) = -2 mA)",
              got is not None and abs(abs(got) - 2.0e-3) / 2.0e-3 < 1e-6, str(got))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
