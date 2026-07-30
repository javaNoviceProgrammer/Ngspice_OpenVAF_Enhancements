#!/usr/bin/env python3
"""Enhancement-375: openvaf-r rejects a loop that provably cannot finish.

WHY THIS EXISTS. A Verilog-A module body must complete one evaluation. A loop
that cannot exit makes that impossible, and the compiler used to PANIC on these
(an `unwrap()` on a loop-exit block that was never created). After the CFG repair
in Enhancement-363 it stopped panicking -- and started emitting a well-formed
36 KB `.osdi` instead. ngspice loads it without complaint and then hangs forever
on the first device evaluation, with no diagnostic at all.

That is strictly WORSE than the crash: a compile-time panic is immediate and
loud, whereas a simulator that never returns just looks slow. Hence a
compile-time diagnostic, which is the only correct answer -- there is no valid
object code for a model that cannot finish an evaluation, and substituting a
value for the unreachable code would invent a device that was never described.

THE ANALYSIS IS SOUND IN THE REJECT DIRECTION. Every bail-out means "say
nothing", so it may miss a hang but must not reject a model that terminates.
The `accept` half of this file is therefore the more important half: it is what
proves the check has not broken working code.

NOT DETECTED, and undecidable in general: a loop whose condition variables are
written, but never toward the exit. Nested loops sharing an index are the classic
case -- `for(i=0;i<10;i=i+1) for(i=0;i<3;i=i+1)` runs forever, while the same
shape with the bounds swapped terminates. Those still reach the simulator.

THE `disable` CASE, which is why three of the reject cases below exist.
`disable <block>` is Verilog-AMS's loop break (LRM 5.4) and it is NOT counted as
an escape here. It works, and keeps working, for a loop that can also finish
normally -- such a loop's condition changes, so the check never looks at it
(`disable_from_finite_loop` below). But as the SOLE exit from a loop whose
condition cannot change it does not work today: the code after the loop is then
reachable only through the `disable` edge and OSDI codegen aborts with
`unreachable!("attempted to read undefined value")` in mir_llvm/src/builder.rs.
Verified on the pre-fix binary for a literal `while (1)`, a constant-folding
`while (1 > 0)` and a non-constant `while (i < 10)` whose `i` is never written --
3/3 crashed. So reporting them here cannot regress a working program, because
there is no such program: it replaces a compiler crash with an actionable error.

`$finish`/`$stop`/`$fatal` DO count as escapes -- unlike `disable`, those compile
today, and breaking them would be a real regression.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF  # noqa: E402

checks = passed = 0

HDR = """`include "disciplines.vams"
module nt(a, c);
  inout a, c;
  electrical a, c;
  parameter integer n = 5;
  analog begin : L
    integer i, j; real s;
    s = 0.0; i = 0; j = 0;
"""
TAIL = """    I(a,c) <+ 1e-3*V(a,c) + 1e-6*s;
  end
endmodule
"""

# (label, body) -- must be REJECTED with the loop diagnostic
REJECT = [
    ("literal `while (1)`",
     "while (1) begin s = s + 1.0; end"),
    ("`while` with no increment",
     "while (i < 10) begin s = s + 1.0; end"),
    ("`for` whose increment writes the wrong variable",
     "for (i = 0; i < 10; j = j + 1) begin s = s + 1.0; end"),
    ("condition on a branch probe, which is fixed per evaluation",
     "while (V(a,c) > -1e30) begin s = s + 1.0; end"),
    ("condition on a parameter, which never changes",
     "while (n > 0) begin s = s + 1.0; end"),
    ("infinite loop nested inside a finite one",
     "for (i = 0; i < 3; i = i + 1) begin while (1) s = s + 1.0; end"),
    # the three that used to be compiler CRASHES, not hangs -- see the header
    ("`disable` as the only exit from `while (1)`",
     "begin : esc while (1) begin s = s + 1.0; if (s > 3.0) disable esc; end end"),
    ("`disable` as the only exit from `while (1 > 0)`",
     "begin : esc while (1 > 0) begin s = s + 1.0; if (s > 3.0) disable esc; end end"),
    ("`disable` as the only exit from an unchanging `while (i < 10)`",
     "begin : esc while (i < 10) begin s = s + 1.0; if (s > 3.0) disable esc; end end"),
]

# (label, body) -- must still COMPILE. This half is what proves nothing broke.
ACCEPT = [
    ("ordinary counted `for`",
     "for (i = 0; i < 10; i = i + 1) begin s = s + 1.0; end"),
    ("`while` that increments in the body",
     "while (i < 10) begin s = s + 1.0; i = i + 1; end"),
    ("`repeat` is counted and always terminates",
     "repeat (10) begin s = s + 1.0; end"),
    ("`while (0)` is a zero-trip loop, not an infinite one",
     "while (0) begin s = s + 1.0; end"),
    ("condition variable written only under an `if`",
     "while (i < 4) begin s = s + 1.0; if (s > 0.0) i = i + 1; end"),
    ("nested loops with distinct indices",
     "for (i = 0; i < 3; i = i + 1) begin for (j = 0; j < 3; j = j + 1) s = s + 1.0; end"),
    ("`do ... while`",
     "do begin s = s + 1.0; i = i + 1; end while (i < 4);"),
    ("`disable` out of a loop that can also finish normally",
     "begin : esc for (i = 0; i < 9; i = i + 1) begin s = s + 1.0; "
     "if (s > 3.0) disable esc; end end"),
    ("`$finish` escapes `while (1)`",
     "while (1) begin s = s + 1.0; if (s > 3.0) $finish; end"),
    ("`$fatal` escapes `while (1)`",
     "while (1) begin s = s + 1.0; if (s > 3.0) $fatal(0, \"x\"); end"),
]


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_body(body, tag):
    d = os.path.join(HERE, "_vl_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "nt.va"), "w").write(HDR + "    " + body + "\n" + TAIL)
    # RAYON_NUM_THREADS=1 keeps panic sites deterministic; a per-job TMPDIR stops
    # parallel compiles colliding. Both learned from earlier openvaf campaigns.
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    try:
        r = subprocess.run([OPENVAF, "nt.va", "-o", "nt.osdi"], cwd=d, env=env,
                           capture_output=True, text=True, timeout=300, errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return -9, "the COMPILER hung"


def main():
    for i, (label, body) in enumerate(REJECT):
        rc, out = compile_body(body, "r%d" % i)
        diagnosed = "loop condition" in out
        # A crash (rc 101) or a hang must NOT count as a pass: the whole point is
        # to replace those with a clean diagnostic.
        crashed = "OpenVAF encountered a problem" in out or rc == 101
        check("reject: %s" % label, diagnosed and not crashed,
              "rc=%d %s" % (rc, "CRASHED" if crashed else
                            ("diagnosed" if diagnosed else "compiled silently")))

    for i, (label, body) in enumerate(ACCEPT):
        rc, out = compile_body(body, "a%d" % i)
        check("accept: %s" % label, rc == 0,
              "rc=%d%s" % (rc, "" if rc == 0 else " -- FALSE POSITIVE"))

    # The two messages must stay distinguishable: a literal-true condition is
    # certainly infinite, while a merely invariant one is either never entered or
    # never left, and the report must not claim more than it knows.
    _, out_always = compile_body("while (1) begin s = s + 1.0; end", "m0")
    _, out_inv = compile_body("while (i < 10) begin s = s + 1.0; end", "m1")
    check("a constant-true condition is reported as always true",
          "always true" in out_always, "'loop condition is always true'")
    check("a merely invariant condition is not called always true",
          "can never change" in out_inv and "always true" not in out_inv,
          "'loop condition can never change'")

    for j in os.listdir(HERE):
        if j.startswith("_vl_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
