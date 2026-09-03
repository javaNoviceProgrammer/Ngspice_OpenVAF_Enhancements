#!/usr/bin/env python3
"""Enhancement-522: analog events, audited against Accellera VAMS-2023
clause 5.10, then fixed.

What this suite pins, each against the quoted clause:

  * 5.10.2 / Table 5-1 -- phase-qualified step events, EXACT per analysis.
    The operating point of an .ac/.noise job carried the "dc" analysis
    name, so @(initial_step("dc")) fired there (the table says 0 for every
    AC and NOISE point), and a noise run ended answering to "ac", so
    @(final_step("ac")) fired at the end of .noise. LRM Table 4-22 defines
    analysis("dc")/analysis("ac") as 0 at exactly those points too, so the
    shared flag derivation was fixed once for both channels. The whole
    five-analysis matrix (op, dc sweep, tran, ac, noise) is checked here.
  * 5.10.3.2 -- "The cross() function will not generate events for
    non-transient analyses, such as ac, dc, or noise" and "can only
    generate an event after the simulation time has advanced from zero."
    It fired during .dc sweeps and off the Newton iterates of the t=0
    operating point. Gated now -- while its state keeps tracking through
    DC, so the first transient step compares against the converged OP.
    above() DOES fire during initialization and dc sweeps, per the same
    clause -- including the mandated initialization event when the
    expression is positive at the initial solve (it used to fire only when
    the Newton trajectory happened to cross the threshold).
  * 5.10 restrictions, enforced: nested event controls ("not allowed" --
    the nested form was a silently DEAD statement), cross/above under a
    runtime if/case arm or inside repeat/while/for ("shall not be used
    inside an if ... unless the conditional expression is a genvar
    expression"), and analog filters inside the event EXPRESSION (the
    body-side check always existed; the expression side did not).
  * 5.10 -- an unrecognized event expression is a targeted ERROR:
    @(absdelta(...)) (digital-only, 5.10.3.4), @(named_event) (5.10.4,
    outside the analog subset) and plain typos used to silently DROP the
    event control and run the guarded body on EVERY model evaluation.
  * 5.10.1 -- "A comma (,) can be used interchangeably with the keyword
    or" -- it was a parse error.
  * 5.10.3.1 (documented deviation, made audible) -- a NONZERO cross/above
    tolerance is accepted but not honored (detection is
    evaluation-granular); it draws a warning now. 0.0 means "the simulator
    shall apply a suitable value" and stays silent.
"""

import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_lv_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_file(name):
    osdi = os.path.join(HERE, f"_lv_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def compile_src(src, tag):
    va = os.path.join(HERE, f"_lv_{tag}.va")
    with open(va, "w") as f:
        f.write(src)
    return compile_file(os.path.basename(va))


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_lv_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmevents\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
                f"option noacct\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def ev_tags(out):
    return sorted(re.findall(r"EV (\S+?)(?: RESULT.*)?$", out, re.M))


HDR = '`include "disciplines.vams"\n'

# ---- Table 5-1, the whole matrix -------------------------------------------
print("Table 5-1 phase-qualified step events, per analysis:")
rc, out, osdi = compile_file("lrmevents.va")
check("[1] lrmevents.va compiles (comma or-list included)", rc == 0,
      out.strip().splitlines()[-1] if rc else "")
if rc == 0:
    body = "V1 in 0 DC 1 AC 1\nR1 in a 1k\nN1 a 0 mm\n.model mm lrmevents"
    cases = [
        ("op", "op", ["final_step", "final_step(dc)",
                      "initial_step", "initial_step(dc)"]),
        ("dc", "dc V1 0 1 0.1", ["final_step", "final_step(dc)",
                                 "initial_step", "initial_step(dc)"]),
        ("tran", "tran 1u 10u", ["final_step", "final_step(tran)",
                                 "initial_step", "initial_step(tran)"]),
        ("ac", "ac dec 2 1k 100k", ["final_step", "final_step(ac)",
                                    "initial_step", "initial_step(ac)"]),
        ("noise", "noise v(a) V1 dec 2 1k 100k", ["final_step", "final_step(noise)",
                                                  "initial_step", "initial_step(noise)"]),
    ]
    for name, ctl, want in cases:
        sim = run(body, f"{ctl}\nrun" if name == "op" else ctl, name, osdi)
        got = ev_tags(sim)
        check(f"[2] .{name}: exactly {want}", got == sorted(want), f"{got}")

    # cross/above/timer behavior across analyses
    sim = run(body, "dc V1 0 1 0.1", "xdc", osdi)
    m = re.search(r"RESULT ncross=(\d+) nabove=(\d+)", sim)
    check("[3] .dc sweep: cross stays silent (5.10.3.2)",
          m and m.group(1) == "0", m.group(1) if m else None)
    check("[4] .dc sweep: above fires crossing 0.55 from below",
          m and m.group(2) == "1", m.group(2) if m else None)

    sim = run(body, "tran 1u 10u", "xtr", osdi)
    m = re.search(r"RESULT ncross=(\d+) nabove=(\d+) ntimer=(\d+) norlist=(\d+)", sim)
    check("[5] constant 1 V transient: cross has no t=0/Newton event",
          m and m.group(1) == "0", m.group(1) if m else None)
    check("[6] above fires its mandated initialization event exactly once",
          m and m.group(2) == "1", m.group(2) if m else None)
    check("[7] timer(0,1u) over 10u fires 11 times",
          m and m.group(3) == "11", m.group(3) if m else None)
    check("[8] comma or-list = initial_step + timer(2.5u) -> 2",
          m and m.group(4) == "2", m.group(4) if m else None)

# a genuine transient crossing still fires, exactly once
rc, out, osdi = compile_src(HDR + """
module xr(p, n);
  inout p, n; electrical p, n;
  integer nc;
  analog begin
    @(cross(V(p,n) - 0.5, +1)) nc = nc + 1;
    @(final_step) $strobe("RESULT nc=%d", nc);
    I(p,n) <+ 1e-9*V(p,n);
  end
endmodule
""", "xr")
if rc == 0:
    sim = run("V1 a 0 DC 0 PULSE(0 1 2u 1u 1u 4u 10u)\nN1 a 0 mm\n.model mm xr",
              "tran 0.2u 8u", "ramp", osdi)
    m = re.search(r"RESULT nc=(\d+)", sim)
    check("[9] a real rising crossing in a transient fires exactly once",
          m and m.group(1) == "1", m.group(1) if m else None)

# ---- the enforced restrictions ---------------------------------------------
print("\nthe 5.10 restrictions are enforced:")
rc, out, _ = compile_src(HDR + """
module e1(p,n); inout p,n; electrical p,n; integer x;
analog begin
  @(initial_step) @(final_step) x = 1;
  I(p,n) <+ 1e-9*V(p,n);
end
endmodule
""", "nested")
check("[10] nested event controls are an error",
      rc != 0 and "nested event control" in out)

rc, out, _ = compile_src(HDR + """
module e2(p,n); inout p,n; electrical p,n; integer x;
analog begin
  if (V(p,n) > 0) @(cross(V(p,n)-0.5,+1)) x = x + 1;
  I(p,n) <+ 1e-9*V(p,n);
end
endmodule
""", "underif")
check("[11] cross under a runtime if is an error (5.10.3.1)",
      rc != 0 and "not allowed inside a conditional" in out)

rc, out, _ = compile_src(HDR + """
module e3(p,n); inout p,n; electrical p,n; integer x, i;
analog begin
  for (i = 0; i < 3; i = i + 1) @(cross(V(p,n)-0.5,+1)) x = x + 1;
  I(p,n) <+ 1e-9*V(p,n);
end
endmodule
""", "inloop")
check("[12] cross inside a loop is an error",
      rc != 0 and "loop" in out)

rc, out, _ = compile_src(HDR + """
module e4(p,n); inout p,n; electrical p,n; integer x;
analog begin
  @(cross(ddt(V(p,n)) - 1n, +1)) x = x + 1;
  I(p,n) <+ 1e-9*V(p,n);
end
endmodule
""", "filtexpr")
check("[13] an analog filter inside the event EXPRESSION is an error",
      rc != 0 and "ddt" in out)

# ---- invalid events are targeted errors ------------------------------------
print("\nunrecognized events are targeted errors (were run-always):")
rc, out, _ = compile_src(HDR + """
module e5(p,n); inout p,n; electrical p,n; integer x;
analog begin
  @(absdelta(V(p,n), 0.1)) x = x + 1;
  I(p,n) <+ 1e-9*V(p,n);
end
endmodule
""", "absd")
check("[14] @(absdelta) errors citing the digital-only rule",
      rc != 0 and "absdelta" in out and "analog subset" in out)

rc, out, _ = compile_src(HDR + """
module e6(p,n); inout p,n; electrical p,n; integer x;
analog begin
  @(myev) x = x + 1;
  I(p,n) <+ 1e-9*V(p,n);
end
endmodule
""", "named")
check("[15] @(identifier) errors as an invalid analog event",
      rc != 0 and "not a valid analog event" in out)

rc, out, _ = compile_src(HDR + """
module e7(p,n); inout p,n; electrical p,n; integer x;
analog begin
  @(cros(V(p,n)-0.5,+1)) x = x + 1;
  I(p,n) <+ 1e-9*V(p,n);
end
endmodule
""", "typo")
check("[16] a typo'd event name errors instead of running always",
      rc != 0 and "cros" in out)

# ---- the tolerance warning -------------------------------------------------
print("\ncross/above tolerances warn when not honored:")
rc, out, _ = compile_src(HDR + """
module e8(p,n); inout p,n; electrical p,n; integer x;
analog begin
  @(cross(V(p,n)-0.5, +1, 1n)) x = x + 1;
  I(p,n) <+ 1e-9*V(p,n);
end
endmodule
""", "tolw")
check("[17] a nonzero time_tol draws the accepted-but-not-honored warning",
      rc == 0 and "not honored" in out)

rc, out, _ = compile_src(HDR + """
module e9(p,n); inout p,n; electrical p,n; integer x;
analog begin
  @(cross(V(p,n)-0.5, +1, 0.0)) x = x + 1;
  I(p,n) <+ 1e-9*V(p,n);
end
endmodule
""", "tolz")
check("[18] a 0.0 tolerance (LRM: simulator picks) stays silent",
      rc == 0 and "not honored" not in out)

# ---- null arguments (round-4 audit, LRM 5.10.3.1-5.10.3.3) -----------------
print("\nnull arguments mean 'not specified' (round-4 audit):")
rc, out, osdi = compile_src(HDR + """
module na(in, out, smpl, en);
  parameter real thresh = 0.0;
  parameter integer dir = +1 from [-1:+1] exclude 0;
  output out; input in, smpl, en;
  electrical in, out, smpl, en;
  real state; integer cnull, comit, tnull, tomit;
  analog begin
    @(initial_step) begin cnull = 0; comit = 0; tnull = 0; tomit = 0; end
    // the LRM 5.10.3.1 sample-and-hold, in the analog-subset spelling of
    // its enable (a net's digital value is mixed-signal; V(en) is ours)
    @(cross(V(smpl) - thresh, dir, , , V(en) > 0.5))
       state = V(in);
    V(out) <+ transition(state, 0, 10n);
    // null tolerances/enable versus trailing omission: identical events
    @(cross(V(smpl) - 0.5, dir, , , 1)) cnull = cnull + 1;
    @(cross(V(smpl) - 0.5, dir))        comit = comit + 1;
    // a null period is the one-shot form (5.10.3.3)
    @(timer(3u, , , 1)) tnull = tnull + 1;
    @(timer(3u))        tomit = tomit + 1;
    @(final_step) $strobe("NARESULT c=%d/%d t=%d/%d", cnull, comit, tnull, tomit);
    I(in) <+ 1e-9*V(in); I(en) <+ 1e-9*V(en);
  end
endmodule
""", "nullargs")
check("[19] null event arguments compile (LRM sample-and-hold shape)",
      rc == 0, out.strip().splitlines()[-1] if rc else "")
check("[20] null tolerances draw no bogus not-honored warning",
      rc == 0 and "not honored" not in out)
if rc == 0:
    sim = run("V1 a 0 DC 0 PULSE(0 1 2u 1u 1u 4u 10u)\nVen en 0 DC 1\nN1 a b a en mm\n.model mm na",
              "tran 0.2u 8u", "nullargs", osdi)
    m = re.search(r"NARESULT c=(\d+)/(\d+) t=(\d+)/(\d+)", sim)
    check("[21] null tolerances+enable fire identically to the omitted form",
          m and m.group(1) == m.group(2) and m.group(1) == "1",
          m.group(0) if m else "no line")
    check("[22] a null timer period is the one-shot form",
          m and m.group(3) == "1" and m.group(4) == "1", m.group(0) if m else "no line")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
