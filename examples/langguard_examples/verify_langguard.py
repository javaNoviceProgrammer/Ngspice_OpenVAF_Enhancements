#!/usr/bin/env python3
"""Enhancement-395: nine defects from a one-hour hunt aimed at openvaf-r.

Three produce WRONG NUMBERS from code that compiles clean; five are inputs the
compiler should have rejected and silently accepted instead; one is a crash.

  [1] $random AND THE WHOLE $dist_* FAMILY RETURN A CONSTANT INSIDE A LOOP --
      AND THAT IS DELIBERATE, SO IT IS NOW REPORTED RATHER THAN SILENT.

      `for (i=0;i<n;i=i+1) s = s + $dist_normal(seed,0,1);` draws ONE number and
      adds it n times, for every distribution and both the $dist_ and $rdist_
      spellings. A Monte-Carlo model written the obvious way has exactly one
      sample of variation in it.

      The LRM makes `seed` an inout and prescribes advancing it in place. That
      is exactly what Enhancement-10 refused to do, and its design note at
      openvaf/osdi/stdlib.c says why: the draws must be stable across the
      nonlinear solver's Newton iterations, and a seed that advances in place
      changes on every model evaluation. Advancing it was tried here and MEASURED
      -- a model carrying its seed across evaluations with a meaningful spread
      failed dynamic gmin stepping, true gmin stepping, source stepping and the
      transient operating point outright. The wrong-number defect would have
      been traded for a simulator that does not converge.

      So the purity stays and the silence goes: an RNG builtin inside a runtime
      loop now raises the `rng_in_loop` lint, which names the call, says the
      draw is constant within the loop, says why it cannot be otherwise, and
      suggests a separate call site per sample. It is a warning, not an error --
      the code is well formed -- and `(* openvaf_allow="rng_in_loop" *)`
      silences it.

  [2] THREE OF THE FOUR LAPLACE FILTERS USED UNNORMALISED ROOTS.

      LRM 4.5.11 defines the root forms as products of (1 - s/r_k), so a filter
      whose numerator and denominator are given by their roots has DC gain 1.
      `laplace_np`, `laplace_zp` and `laplace_zd` built products of (s - r_k)
      instead, which is the same polynomial scaled by prod(-r_k) -- a DC gain
      wrong by that factor, silently. With a single pole at -1e4 the gain was
      off by 1e4; with two it was off by 1e8. `laplace_nd` was correct, so the
      four forms disagreed with each other on the same filter.

      A zero root is the LRM's stated exception: it contributes a bare `s`
      rather than (1 - s/0). That is now handled explicitly instead of dividing
      by zero.

  [3] RUNTIME $table_model CLAMPED INSTEAD OF EXTRAPOLATING.

      With linear extrapolation requested ("1L" and friends) a query outside
      the grid returned the end VALUE rather than continuing the end SEGMENT's
      slope, whenever the table came from runtime arrays. The slope was taken
      from a segment chosen without regard to which knots were live, so at the
      boundary it could be a degenerate zero-width segment -- and a zero-width
      segment gives slope 0, i.e. a clamp. The end slopes now come from the
      first and last NON-degenerate segments.

  [4] $table_model SILENTLY IGNORED FIVE OF THE LRM'S CONTROL CODES.

      Tables 9-30 and 9-31 define interpolation codes I, D, 1, 2, 3 and
      extrapolation codes C, L, E. `2`, `D`, `I` and `E` were accepted and then
      quietly treated as something else, and two different extrapolation codes
      on the two ends were accepted and only one honoured. A model asking for
      quadratic interpolation got linear and was never told.

      These are rejected now rather than silently substituted. The codes that
      ARE implemented keep working, whitespace and the `;N` suffix included.
      (E-562 implemented `2`, the quadratic spline, for compile-time and
      runtime data alike, so `"2"` moved to the compiling list -- its values are
      pinned in tablesrc_examples; `I` stays refused on runtime arrays.)

  [5] `$discontinuity;` WITH NO ARGUMENT PANICKED THE COMPILER.

      The argument is optional in the LRM (degree defaults to 0) and the
      lowering read args[0] unconditionally.

  [6] AN ACCESS FUNCTION FROM A FOREIGN DISCIPLINE SILENTLY ALIASED THE NATIVE
      ONE.

      `Zi(p,n)` on an `electrical` branch behaved exactly as `I(p,n)` as long as
      ZCur happened to declare `units = "A"`. The resolver asked whether the
      natures were compatible, and `compatible` compares UNITS STRINGS and
      nothing else -- so it could tell a potential from a flow but not which
      discipline the access function belonged to. It asks whether they are
      RELATED now (share a base nature), which is the LRM's own rule and still
      admits every nature DERIVED from a discipline's own.

  [7] GENVARS COLLIDING WITH A DECLARED NAME WERE NOT DIAGNOSED.

  [8] INSTANTIATION VALIDATION HOLES left by Enhancement-392: a duplicate named
      port, a duplicate named parameter, and a connection list that mixes
      positional and named form were all accepted.

  [9] SETTING A PARAMETER AND ITS `aliasparam` TO DIFFERENT VALUES WAS SILENT.

      An OSDI parameter and each of its alias names are registered as separate
      IFparm entries carrying the SAME id, so `N1 a 0 md w=1 width=4` writes
      one slot twice and one spelling silently loses. Setting one name twice
      does the same. Both are reported now, at the instance line and on the
      model card.

      The model-card message deliberately does not say WHICH value wins,
      because the two channels on a card disagree: a model parameter is written
      straight through so the last wins, while an instance-parameter default is
      pushed with wl_cons and replayed in reverse, so the first wins. Naming a
      winner would be wrong half the time.

WITHDRAWN during the fix, recorded because the evidence matters: a parameter
whose DEFAULT lies outside its own declared range is deliberately not
range-checked (Enhancement-56). Real compact models rely on it -- diode_cmc
declares `CORECOVERY = 0.0 from (0.0:1.0]` and gates on `if (CORECOVERY > 0)`,
using the out-of-range default to mean "feature disabled".

Every check below is paired: the reject half pins the defect, and the accept
half pins that legitimate input still compiles and still gives the same number.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0
HDR = '`include "disciplines.vams"\n'


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(src, tag, extra=None):
    d = os.path.join(HERE, "_op_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    for name, content in (extra or {}).items():
        open(os.path.join(d, name), "w").write(content)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def run(d, deck, guard=60):
    open(os.path.join(d, "q.cir"), "w").write(deck)
    r = subprocess.run(["perl", "-e", f"alarm {guard}; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def vals(out, name):
    return [float(m) for m in
            re.findall(rf"^{re.escape(name)}\s*=\s*([-+0-9.eE]+)", out, re.M)]


def op(d, net, card="dut()", body="op\nprint i(v1)", extra="", src="V1 a 0 dc 1"):
    deck = ("p\n.control\npre_osdi m.osdi\n.endc\n" + src + "\n" + net + "\n"
            ".model md " + card + "\n" + extra +
            "\n.control\noption noacct\nset numdgt=12\n" + body + "\n.endc\n.end\n")
    return run(d, deck)


def close(a, b, tol=1e-9):
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))


# ---------------------------------------------------------------- [5] crash
DISCONT = HDR + """
module dut(p,n);
 inout p,n; electrical p,n;
 parameter real r0 = 1000;
 analog begin
   $discontinuity;
   $discontinuity(0);
   $discontinuity(1);
   if (V(p,n) > 1e9) $discontinuity;
   I(p,n) <+ V(p,n)/r0;
 end
endmodule
"""

# ---------------------------------------------------------------- [1] rng
RNG_TMPL = HDR + """
module dut(p,n);
 inout p,n; electrical p,n;
 parameter integer nsamp = 64;
 (* desc="spread" *) real spread;
 integer i, seed;
 real lo, hi, x;
 analog begin
   seed = 91; lo = 1e30; hi = -1e30;
   for (i = 0; i < nsamp; i = i + 1) begin
     x = %s;
     if (x < lo) lo = x;
     if (x > hi) hi = x;
   end
   spread = hi - lo;
   I(p,n) <+ V(p,n)*1e-3;
 end
endmodule
"""

# ---------------------------------------------------------------- [2] laplace
LAPLACE = HDR + """
module dut(p,n);
 inout p,n; electrical p,n;
 parameter integer form = 0;
 real y;
 analog begin
   // H(s) = (1 + s/1e5) / (1 + s/1e4) -- DC gain exactly 1, written four ways
   if (form == 0)      y = laplace_nd(V(p,n), '{1.0, 1.0e-5}, '{1.0, 1.0e-4});
   else if (form == 1) y = laplace_np(V(p,n), '{1.0, 1.0e-5}, '{-1.0e4, 0.0});
   else if (form == 2) y = laplace_zp(V(p,n), '{-1.0e5, 0.0}, '{-1.0e4, 0.0});
   else                y = laplace_zd(V(p,n), '{-1.0e5, 0.0}, '{1.0, 1.0e-4});
   I(p,n) <+ y*1e-3;
 end
endmodule
"""

# ---------------------------------------------------------------- [3] table
# A runtime table's arrays have a FIXED declared size, so a model with fewer
# distinct knots than slots leaves REPEATED abscissae -- which Enhancement-391
# compacts to the end of the array. Those repeats are the zero-width segments
# that the end-slope search used to land on. `dup` puts them at the top end,
# `duplo` at the bottom.
TABLE = HDR + """
module dut(p,n);
 inout p,n; electrical p,n;
 parameter real xq = 0.0;
 parameter integer dup = 0;
 parameter integer duplo = 0;
 (* desc="y" *) real y;
 real gx[0:5], gy[0:5];
 analog begin
   if (duplo) begin
     gx[0]=0.0; gx[1]=0.0; gx[2]=0.0; gx[3]=1.0; gx[4]=2.0; gx[5]=3.0;
     gy[0]=0.0; gy[1]=0.0; gy[2]=0.0; gy[3]=2.0; gy[4]=4.0; gy[5]=6.0;
   end else if (dup) begin
     gx[0]=0.0; gx[1]=1.0; gx[2]=2.0; gx[3]=3.0; gx[4]=3.0; gx[5]=3.0;
     gy[0]=0.0; gy[1]=2.0; gy[2]=4.0; gy[3]=6.0; gy[4]=6.0; gy[5]=6.0;
   end else begin
     gx[0]=0.0; gx[1]=0.6; gx[2]=1.2; gx[3]=1.8; gx[4]=2.4; gx[5]=3.0;
     gy[0]=0.0; gy[1]=1.2; gy[2]=2.4; gy[3]=3.6; gy[4]=4.8; gy[5]=6.0;
   end
   y = $table_model(xq, gx, gy, "1L");
   I(p,n) <+ V(p,n)*1e-3;
 end
endmodule
"""

# ---------------------------------------------------------------- [6] access
NATURES = """
nature ZCur;  units="A"; access=Zi; abstol=1e-12; endnature
nature ZVlt;  units="V"; access=Zv; abstol=1e-6;  endnature
discipline zd; potential ZVlt; flow ZCur; enddiscipline
"""

# ---------------------------------------------------------------- [9] alias
ALIAS = HDR + """
module dut(p,n);
 inout p,n; electrical p,n;
 (*type="instance"*) parameter real w = 1.0 from (0:inf);
 aliasparam width = w;
 (*type="instance"*) parameter real g = 1e-3;
 analog I(p,n) <+ V(p,n)*g*w;
endmodule
"""


LEAF = """
module leaf(a,b);
 inout a,b; electrical a,b;
 analog I(a,b) <+ V(a,b)/1000.0;
endmodule
"""


def main():
    # =================================================== [5] $discontinuity
    print("\n  -- [5] `$discontinuity;` with no argument --")
    d, rc, out = build(DISCONT, "disc")
    check("all four $discontinuity forms compile", rc == 0,
          (out.strip().splitlines() or [""])[0][:70])
    check("the compiler did not panic", "panicked" not in out and "internal error" not in out)
    if rc == 0:
        rc2, o = op(d, "N1 a 0 md")
        v = vals(o, "i(v1)")
        check("and the model simulates", close(v[0] if v else None, -1e-3), f"{v}")

    # =================================================== [1] RNG in a loop
    print("\n  -- [1] $random / $dist_* inside a loop --")
    LOOP = HDR + """
module dut(p,n);
 inout p,n; electrical p,n;
 parameter integer nsamp = 8;
 integer i, seed;
 real s, x;
 analog begin
   seed = 91; s = 0.0;
   for (i = 0; i < nsamp; i = i + 1) begin
     x = %s;
     s = s + x;
   end
   I(p,n) <+ V(p,n)*1e-3;
 end
endmodule
"""
    DISTS = ["$dist_uniform(seed,0,1000)", "$dist_normal(seed,0,1000)",
             "$dist_exponential(seed,1000)", "$dist_poisson(seed,1000)",
             "$dist_chi_square(seed,50)", "$dist_t(seed,50)",
             "$dist_erlang(seed,7,1000)", "$rdist_uniform(seed,0,1000)",
             "$rdist_normal(seed,0,1000)", "$random(seed)"]
    for expr in DISTS:
        tag = expr.split("(")[0].lstrip("$")
        _d, rc2, o = build(LOOP % expr, "rng_" + tag)
        warned = "same number every iteration" in o
        check(f"{tag} in a loop is reported, not silent", warned and rc2 == 0,
              "no warning" if not warned else f"rc={rc2}")

    # accept half -- the lint must be a WARNING, must not fire outside a loop,
    # and must be silenceable.
    _d, rc2, o = build(LOOP % "$dist_normal(seed,0,1000)", "rng_build")
    check("a warned model still compiles (lint, not error)",
          rc2 == 0 and os.path.exists(os.path.join(_d, "m.osdi")), f"rc={rc2}")

    NOLOOP = HDR + """
module dut(p,n);
 inout p,n; electrical p,n;
 integer seed;
 real x;
 analog begin
   seed = 91;
   x = $dist_normal(seed,0,1);
   I(p,n) <+ V(p,n)*1e-3*(1.0 + x*0.0);
 end
endmodule
"""
    _d, rc2, o = build(NOLOOP, "rng_noloop")
    check("a draw OUTSIDE a loop is not reported",
          rc2 == 0 and "same number every iteration" not in o)

    SILENCED = LOOP.replace("     x = %s;", '     (* openvaf_allow="rng_in_loop" *) x = %s;')
    _d, rc2, o = build(SILENCED % "$dist_normal(seed,0,1000)", "rng_allow")
    check("openvaf_allow=\"rng_in_loop\" silences it",
          rc2 == 0 and "same number every iteration" not in o)

    # THE REASON the draw must stay pure: a model that CARRIES its seed across
    # evaluations must still converge. Advancing the seed in place broke this.
    CARRY = HDR + """
module dut(p,n);
 inout p,n; electrical p,n;
 integer seed;
 real x;
 analog begin
   @(initial_step) seed = 91;
   x = $rdist_normal(seed, 1.0, 0.5);
   I(p,n) <+ V(p,n)*1e-3*x;
 end
endmodule
"""
    _d, rc2, o = build(CARRY, "rng_carry")
    check("the carried-seed model compiles", rc2 == 0,
          (o.strip().splitlines() or [""])[0][:60])
    if rc2 == 0:
        for label, body in [("operating point", "op\nprint i(v1)"),
                            ("transient", "tran 2u 10u\nprint i(v1)"),
                            ("dc sweep", "dc v1 0 1 0.1\nprint i(v1)")]:
            rc3, oo = op(_d, "N1 a 0 md", body=body)
            broke = [ln.strip() for ln in oo.splitlines()
                     if re.search(r"gmin stepping|source stepping|timestep too small"
                                  r"|could not be simulated", ln, re.I)]
            check(f"a seed carried across evaluations still converges in {label}",
                  not broke, (broke or [""])[0][:56])

    # =================================================== [2] laplace
    print("\n  -- [2] laplace filters built from roots --")
    d, rc, out = build(LAPLACE, "lap")
    check("the four-form laplace model compiles", rc == 0,
          (out.strip().splitlines() or [""])[0][:70])
    if rc == 0:
        # DC gain of a one-pole-at--1e4 filter is 1, so i(v1) = -1e-3.
        got = {}
        for form, name in [(0, "nd"), (1, "np"), (2, "zp"), (3, "zd")]:
            rc2, o = op(d, "N1 a 0 md", card=f"dut(form={form})", src="V1 a 0 dc 1 ac 1",
                        body="ac dec 5 1 1e6\nprint mag(i(v1))[0]")
            v = vals(o, "mag(i(v1))[0]") or vals(o, "mag(i(v1))")
            got[name] = v[0] if v else None
        for name in ("np", "zp", "zd"):
            check(f"laplace_{name} has DC gain 1 like laplace_nd",
                  got["nd"] not in (None, 0.0) and close(got[name], got["nd"], 1e-9),
                  f"{name}={got[name]} nd={got['nd']}")
        check("and that gain is 1e-3, not scaled by the root product",
              close(got["nd"], 1e-3, 1e-9), f"{got}")

        # the whole response, not just DC: np must track nd across the sweep
        rc2, o1 = op(d, "N1 a 0 md", card="dut(form=0)", src="V1 a 0 dc 1 ac 1",
                     body="ac dec 4 1 1e6\nprint mag(i(v1))")
        rc3, o2 = op(d, "N1 a 0 md", card="dut(form=1)", src="V1 a 0 dc 1 ac 1",
                     body="ac dec 4 1 1e6\nprint mag(i(v1))")
        a = re.findall(r"^\s*\d+\s+[-+0-9.eE]+\s+([-+0-9.eE]+)", o1, re.M)
        b = re.findall(r"^\s*\d+\s+[-+0-9.eE]+\s+([-+0-9.eE]+)", o2, re.M)
        ok = len(a) > 10 and len(a) == len(b) and any(float(x) != 0.0 for x in a) and all(
            abs(float(x) - float(y)) <= 1e-12 * max(1e-30, abs(float(x))) for x, y in zip(a, b))
        check("np matches nd at every frequency in the sweep, not only at DC",
              ok, f"{len(a)} points")

    # the LRM's zero-root exception: a root at the origin is a bare `s`
    d, rc, out = build(HDR + """
module dut(p,n);
 inout p,n; electrical p,n;
 parameter integer form = 0;
 real y;
 analog begin
   // a zero AT THE ORIGIN: H(s) = s / (1 + s/1e4)
   if (form == 0) y = laplace_zd(V(p,n), '{0.0, 0.0}, '{1.0, 1.0e-4});
   else           y = laplace_nd(V(p,n), '{0.0, 1.0}, '{1.0, 1.0e-4});
   I(p,n) <+ y*1e-3;
 end
endmodule
""", "lap0")
    check("a laplace filter with a root AT the origin compiles", rc == 0,
          (out.strip().splitlines() or [""])[0][:70])
    if rc == 0:
        g = []
        for form in (0, 1):
            rc2, o = op(d, "N1 a 0 md", card=f"dut(form={form})", src="V1 a 0 dc 1 ac 1",
                        body="ac dec 5 1e2 1e5\nprint mag(i(v1))[3]")
            v = vals(o, "mag(i(v1))[3]") or vals(o, "mag(i(v1))")
            g.append(v[0] if v else None)
        check("a zero root gives a bare `s`, matching the same filter written nd",
              g[1] not in (None, 0.0) and close(g[0], g[1], 1e-9), f"zd={g[0]} nd={g[1]}")

    # =================================================== [3] table extrapolation
    print("\n  -- [3] runtime $table_model linear extrapolation --")
    d, rc, out = build(TABLE, "tab")
    check("the runtime-array table model compiles", rc == 0,
          (out.strip().splitlines() or [""])[0][:70])
    if rc == 0:
        # y = 2x on [0,3] in every variant, so "1L" must continue slope 2 on
        # both sides no matter where the repeated knots sit.
        for tag, card_extra in [("a clean grid", ""),
                                ("repeats at the TOP end", " dup=1"),
                                ("repeats at the BOTTOM end", " duplo=1")]:
            for xq, want in [(-2.0, -4.0), (-0.5, -1.0), (0.0, 0.0), (1.5, 3.0),
                             (3.0, 6.0), (4.0, 8.0), (7.5, 15.0)]:
                rc2, o = op(d, "N1 a 0 md", card=f"dut(xq={xq}{card_extra})",
                            body="op\nprint @n1[y]")
                v = vals(o, "@n1[y]")
                check(f"{tag}: x={xq:g} gives {want:g}",
                      close(v[0] if v else None, want, 1e-9), f"{v}")

    # =================================================== [4] table control codes
    print("\n  -- [4] $table_model control string --")

    def tbl_ctrl(ctrl):
        src = HDR + """
module dut(p,n);
 inout p,n; electrical p,n;
 real gx[0:2], gy[0:2];
 real y;
 analog begin
   gx[0]=0.0; gx[1]=1.0; gx[2]=2.0;
   gy[0]=0.0; gy[1]=1.0; gy[2]=4.0;
   y = $table_model(V(p,n), gx, gy, "%s");
   I(p,n) <+ y*1e-3;
 end
endmodule
""" % ctrl
        _d, _rc, _o = build(src, "tc")
        return _rc, _o

    for ctrl in ["D", "I", "E", "1E", "1CL", "1LC", "3CL", "Q"]:
        rc2, o = tbl_ctrl(ctrl)
        check(f'control "{ctrl}" is rejected rather than silently substituted',
              rc2 != 0, (o.strip().splitlines() or [""])[0][:60])
    for ctrl in ["1", "1L", "1C", "3L", "3C", "1L,1L", "3C,3C", "1;5", "3 L",
                 " 1L ", "1L ,1L", "3", "3;2", "1C,1C",
                 "1C,1L", "1L,1C", "1CC", "3LL", "2", "2L", "3,2"]:
        rc2, o = tbl_ctrl(ctrl)
        check(f'control "{ctrl}" still compiles', rc2 == 0,
              (o.strip().splitlines() or [""])[0][:60])

    # =================================================== [6] foreign access
    print("\n  -- [6] access function from a foreign discipline --")
    for label, body, want_reject in [
        ("foreign flow Zi() on an electrical branch",
         "analog Zi(p,n) <+ V(p,n)*1e-3;", True),
        ("foreign potential Zv() on an electrical branch",
         "analog I(p,n) <+ Zv(p,n)*1e-3;", True),
    ]:
        src = HDR + NATURES + "module dut(p,n); inout p,n; electrical p,n; " + body + " endmodule\n"
        _d, rc2, o = build(src, "acc")
        check(label + " is rejected", rc2 != 0, (o.strip().splitlines() or [""])[0][:60])

    for label, src, want in [
        ("native I()/V() on electrical",
         HDR + "module dut(p,n); inout p,n; electrical p,n; analog I(p,n) <+ V(p,n)*1e-3; endmodule\n",
         -1e-3),
        ("a custom discipline using its OWN access functions",
         HDR + NATURES + "module dut(p,n); inout p,n; zd p,n; analog Zi(p,n) <+ Zv(p,n)*1e-3; endmodule\n",
         -1e-3),
        ("a nature DERIVED from Voltage still resolves",
         HDR + "nature MyV : Voltage; abstol=1e-9; endnature\n"
               "discipline myd; potential MyV; flow Current; enddiscipline\n"
               "module dut(p,n); inout p,n; myd p,n; analog I(p,n) <+ V(p,n)*1e-3; endmodule\n",
         -1e-3),
        ("the standard thermal discipline",
         HDR + "module dut(p,n); inout p,n; thermal p,n; analog Pwr(p,n) <+ Temp(p,n)*1e-3; endmodule\n",
         -1e-3),
    ]:
        _d, rc2, o = build(src, "accok")
        if rc2 != 0:
            check(label + " still compiles", False, (o.strip().splitlines() or [""])[0][:60])
            continue
        rc3, oo = op(_d, "N1 a 0 md")
        v = vals(oo, "i(v1)")
        check(label + " still compiles and gives the same answer",
              close(v[0] if v else None, want), f"{v}")

    # =================================================== [7] genvar collisions
    print("\n  -- [7] genvar colliding with a declared name --")
    for label, decl in [
        ("genvar vs a parameter", "parameter real k = 1.0;"),
        ("genvar vs a real variable", "real k;"),
        ("genvar vs an integer variable", "integer k;"),
        ("genvar vs a net", "electrical k;"),
    ]:
        src = HDR + LEAF + """
module dut(p,n);
 inout p,n; electrical p,n;
 %s
 genvar k;
 electrical [0:3] mid;
 generate
   for (k = 0; k < 3; k = k + 1) begin : seg
     leaf lk(mid[k], mid[k+1]);
   end
 endgenerate
 analog I(p,n) <+ V(p,n)*1e-4;
endmodule
""" % decl
        _d, rc2, o = build(src, "gv")
        check(label + " is rejected", rc2 != 0, (o.strip().splitlines() or [""])[0][:60])

    src = HDR + LEAF + """
module dut(p,n);
 inout p,n; electrical p,n;
 genvar k;
 electrical [0:3] mid;
 generate
   for (k = 0; k < 3; k = k + 1) begin : seg
     leaf lk(mid[k], mid[k+1]);
   end
 endgenerate
 analog begin
   V(p, mid[0]) <+ 0.0;
   V(mid[3], n) <+ 0.0;
 end
endmodule
"""
    _d, rc2, o = build(src, "gvok")
    check("a genvar loop with no collision still compiles", rc2 == 0,
          (o.strip().splitlines() or [""])[0][:60])
    if rc2 == 0:
        rc3, oo = op(_d, "N1 a 0 md")
        v = vals(oo, "i(v1)")
        check("and the three-segment 1k ladder gives -3.333333e-04",
              close(v[0] if v else None, -1.0/3000.0, 1e-6), f"{v}")

    # =================================================== [8] instantiation holes
    print("\n  -- [8] module instantiation validation --")
    CHILD = """
module leaf(a,b);
 inout a,b; electrical a,b;
 parameter real g = 1e-3;
 parameter real h = 1.0;
 analog I(a,b) <+ V(a,b)*g*h;
endmodule
"""
    for label, inst, want_reject in [
        ("a duplicate named port", "leaf i1(.a(p), .a(n));", True),
        ("a duplicate named parameter", "leaf #(.g(1e-3), .g(2e-3)) i1(.a(p), .b(n));", True),
        ("a connection list mixing positional and named form", "leaf i1(p, .b(n));", True),
        ("a named list, correct", "leaf i1(.a(p), .b(n));", False),
        ("a positional list, correct", "leaf i1(p, n);", False),
        ("named parameters, correct", "leaf #(.g(1e-3), .h(1.0)) i1(.a(p), .b(n));", False),
        ("a partially connected named list", "leaf i1(.a(p));", False),
        ("positional parameters", "leaf #(1e-3, 1.0) i1(p, n);", False),
    ]:
        src = HDR + CHILD + """
module dut(p,n);
 inout p,n; electrical p,n;
 %s
endmodule
""" % inst
        _d, rc2, o = build(src, "inst")
        if want_reject:
            check(label + " is rejected", rc2 != 0, (o.strip().splitlines() or [""])[0][:60])
        else:
            check(label + " still compiles", rc2 == 0, (o.strip().splitlines() or [""])[0][:60])

    # =================================================== [9] aliasparam
    print("\n  -- [9] a parameter and its aliasparam both set --")
    d, rc, out = build(ALIAS, "alias")
    check("the aliasparam model compiles", rc == 0,
          (out.strip().splitlines() or [""])[0][:70])
    if rc == 0:
        def dup(inst, card):
            rc2, o = op(d, inst, card=card)
            warns = [ln.strip() for ln in o.splitlines()
                     if re.search(r"aliasparam|set more than once", ln, re.I)]
            return warns, vals(o, "i(v1)")

        for label, inst, card in [
            ("instance line: w= and its alias width=", "N1 a 0 md w=1 width=4", "dut()"),
            ("instance line: the same name twice", "N1 a 0 md w=1 w=4", "dut()"),
            ("instance line: alias first, then the original", "N1 a 0 md width=1 w=4", "dut()"),
            ("model card: w= and its alias width=", "N1 a 0 md", "dut(w=1 width=4)"),
            ("model card: the same name twice", "N1 a 0 md", "dut(g=1e-3 g=2e-3)"),
        ]:
            w, v = dup(inst, card)
            check(label + " is reported", bool(w), (w or [""])[0][:64])

        for label, inst, card, want in [
            ("an instance overriding a model-card default", "N1 a 0 md width=4", "dut(w=1)", -4e-3),
            ("the alias alone on the instance line", "N1 a 0 md width=4", "dut()", -4e-3),
            ("the original alone on the instance line", "N1 a 0 md w=4", "dut()", -4e-3),
            ("the alias alone on the model card", "N1 a 0 md", "dut(width=4)", -4e-3),
            ("two distinct parameters on one line", "N1 a 0 md w=4 g=2e-3", "dut()", -8e-3),
            ("no parameters at all", "N1 a 0 md", "dut()", -1e-3),
        ]:
            w, v = dup(inst, card)
            check(label + " stays silent and gives the same answer",
                  not w and close(v[0] if v else None, want), f"warn={w} {v}")

    for j in os.listdir(HERE):
        if j.startswith("_op_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    sys.exit(main())
