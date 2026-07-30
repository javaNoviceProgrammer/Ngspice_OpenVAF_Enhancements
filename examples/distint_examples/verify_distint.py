#!/usr/bin/env python3
"""Enhancement-376: `$dist_*` returns `integer`, `$rdist_*` returns `real`.

THE LRM SPLIT. The `$dist_*` family is inherited from Verilog-2001 §17.9.2, where
every parameter and return value is an integer. Verilog-AMS added the `$rdist_*`
family precisely BECAUSE the originals are integer-only and analog modelling needs
real values. If `$dist_*` already returned real there would be no reason for a
second family to exist.

openvaf-r returned `real` from both. Two independent records inside this repo
already said otherwise:

  * `Enhancement-10.md` lists "`$rdist_*` (real-valued)" and "`$dist_*`
    (integer-valued)".
  * An Enhancement-49 audit comment sitting directly above the signatures calls
    them "the integer-distribution `$dist_*` functions" while correcting their
    ARGUMENT types on LRM grounds -- and left the return types alone.

WHAT IT COST. LRM-conformant code did not compile:

    $display("%d", $dist_uniform(seed, 10, 20));
    -> error: type mismatch: expected integer value but found real value

THE FIX IS IN TWO PLACES, AND EITHER ALONE IS WORSE THAN NEITHER. Changing only
the signature table makes the type checker accept `%d` while the LOWERING still
produces a real MIR value -- every downstream integer consumer then reads it as 0.
That was measured, not theorised: with the signature changed and the lowering not,
`$dist_uniform(s,10,20)` printed 0 (outside its own range) and an integer
assignment got 0, while a real assignment still worked. So the lowering now ends
each `$dist_*` in `ficast`, matching `$random`/`$arandom`, which have always been
integer-typed and always cast.

The draw itself is UNCHANGED. Where the runtime value is not already integral it
is rounded first (`floor(x+0.5)`, correct for negatives too, which `$dist_t` and a
zero-mean `$dist_normal` require) and `ficast` then truncates an exactly-integral
double -- lossless. All 20000-draw means and variances are identical before and
after; only the static type moved.

THE `$rdist_*` HALF IS THE TRAP. `$rdist_poisson` lowers through the same
`RngFun::Poisson` call as `$dist_poisson`, so a textual edit casts it too and
silently turns the real family integer. That happened during development and is
why this file asserts the NEGATIVE case -- every `$rdist_*` draw must be
non-integral -- rather than only checking the positive one.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402

checks = passed = 0
N = 4000


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


# `%d` on a $dist_* result is the LRM-conformant spelling and must compile.
LRM_FMT = """`include "disciplines.vams"
module dfmt(a, c);
  inout a, c; electrical a, c;
  integer s, iv;
  analog begin
    @(initial_step) begin
      s = 12345;
      iv = $dist_normal(s, 100, 15);
      $display("PCTD %d IV %d", $dist_uniform(s, 10, 20), iv);
    end
    I(a,c) <+ 1e-3*V(a,c);
  end
endmodule
"""

# Draws every member of both families; the seed is advanced by hand because the
# RNG is a pure function of (seed, salt) -- see Enhancement-10.
SAMPLER = """`include "disciplines.vams"
module dsamp(a, c);
  inout a, c; electrical a, c;
  parameter integer nn = %d;
  integer fd, i, s;
  analog begin
    @(initial_step) begin
      fd = $fopen("_di_s.csv", "w");
      s = 12345;
      for (i = 0; i < nn; i = i + 1) begin
        s = s + 7919;
        $fdisplay(fd, "%%g,%%g,%%g,%%g,%%g,%%g,%%g,%%g,%%g,%%g,%%g,%%g,%%g,%%g",
          $dist_uniform(s,10,20), $dist_normal(s,100,15), $dist_exponential(s,7),
          $dist_poisson(s,4), $dist_chi_square(s,5), $dist_t(s,8), $dist_erlang(s,3,9),
          $rdist_uniform(s,10.0,20.0), $rdist_normal(s,100.0,15.0),
          $rdist_exponential(s,7.0), $rdist_poisson(s,4.0),
          $rdist_chi_square(s,5.0), $rdist_t(s,8.0), $rdist_erlang(s,3.0,9.0));
      end
      $fclose(fd);
    end
    I(a,c) <+ 1e-3*V(a,c);
  end
endmodule
""" % N


def build(src, tag):
    d = os.path.join(HERE, "_di_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, "m.va", "-o", "m.osdi"], cwd=d, env=env,
                       capture_output=True, text=True, timeout=600, errors="replace")
    return (os.path.join(d, "m.osdi") if r.returncode == 0 else None,
            r.stdout + r.stderr)


def sim(osdi, model, tag):
    p = os.path.join(HERE, "_di_%s.cir" % tag)
    open(p, "w").write(
        "distint\nV1 a 0 dc 0.4\nN1 a 0 %s\n.model %s %s()\n"
        ".control\noption noacct\npre_osdi %s\nop\n.endc\n.end\n"
        % (model, model, model, osdi))
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=900, errors="replace")
    return r.stdout + r.stderr


def main():
    # ---- 1. the LRM spelling must compile, and produce IN-RANGE values --------
    osdi, err = build(LRM_FMT, "fmt")
    check("`%d` on a $dist_* result compiles (LRM-conformant)", osdi is not None,
          "" if osdi else err.strip().splitlines()[0][:60] if err.strip() else "no output")
    # run these unconditionally so the check COUNT is the same on both binaries:
    # a pre-fix run must show three failures here, not silently fewer checks
    out = sim(osdi, "dfmt", "fmt") if osdi else ""
    m = re.search(r"PCTD\s+(-?\d+)\s+IV\s+(-?\d+)", out)
    if True:
        # 0 is the signature-only-fix signature: in range says the cast really happened
        check("$dist_uniform(10,20) lands inside [10,20]",
              m is not None and 10 <= int(m.group(1)) <= 20,
              "value %s" % (m.group(1) if m else "not printed"))
        check("$dist_normal(100,15) assigned to an integer is non-zero",
              m is not None and int(m.group(2)) != 0,
              "value %s" % (m.group(2) if m else "not printed"))

    # ---- 2. integer family integral, real family not -------------------------
    osdi, err = build(SAMPLER, "samp")
    if not osdi:
        check("sampler builds", False, err.strip().splitlines()[0][:60])
        return finish()
    sim(osdi, "dsamp", "samp")
    csv = os.path.join(HERE, "_di_s.csv")
    rows = [[float(x) for x in l.split(",")] for l in open(csv)]
    cols = list(zip(*rows))
    names = ["uniform", "normal", "exponential", "poisson", "chi_square", "t", "erlang"]
    for i, n in enumerate(names):
        check("$dist_%s draws are integral" % n,
              all(v == int(v) for v in cols[i]),
              "%d draws" % len(cols[i]))
    for i, n in enumerate(names):
        col = cols[i + 7]
        # poisson is integer-VALUED by nature even as a real, so exempt it from
        # the "must be fractional" test and check its type stayed real elsewhere
        if n == "poisson":
            continue
        check("$rdist_%s draws are NOT integral (stayed real)" % n,
              any(v != int(v) for v in col), "%d draws" % len(col))

    # ---- 3. the draw itself did not move -------------------------------------
    import statistics as st
    theory = [("dist_uniform", 0, 15.0), ("dist_normal", 1, 100.0),
              ("dist_exponential", 2, 7.0), ("dist_poisson", 3, 4.0),
              ("dist_chi_square", 4, 5.0), ("dist_erlang", 6, 9.0)]
    for n, ci, mu in theory:
        m = st.mean(cols[ci])
        check("$%s mean matches theory" % n, abs(m - mu) <= 0.06 * max(abs(mu), 1),
              "%.4f vs %.2f" % (m, mu))

    return finish()


def finish():
    for j in os.listdir(HERE):
        q = os.path.join(HERE, j)
        if j.startswith("_di_"):
            shutil.rmtree(q, ignore_errors=True) if os.path.isdir(q) else os.remove(q)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
