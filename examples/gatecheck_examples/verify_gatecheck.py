#!/usr/bin/env python3
"""Enhancement-480: a check that could not fire where it mattered.

Bug-hunt round 49. Most of these are not missing checks -- the check was
written, and something upstream of it made it unreachable:

  * the duplicate-parameter test on a `.model` card was gated on the tracking
    list not being FULL, so a device with one model parameter could never
    report a repeat at all;
  * the same test counted the model TYPE token as a parameter, so
    `.model rmod r(r=1k)` -- the most ordinary card there is -- was told
    "parameter 'r' is set more than once ... remove one";
  * the limiter's reversed-limits message was gated on `TIME != 0`, which is
    never true in an `op` or a `dc` sweep, so it said nothing there and said it
    214 times in a transient;
  * the unterminated-block check ran per LINE of a `.control` section, never at
    the end of the section, so an `if` with no `end` swallowed every command
    after it and exited 0 in silence;
  * `.measure`'s edge count reached a struct whose "not given" and "LAST"
    sentinels are -1 and -2, so a written `fall=-1` was read as "no fall given"
    and answered with a RISING edge.

The rest are guards that were genuinely absent (a transmission line's `nl/f`,
a switch's hysteresis, the code-model PWL's breakpoint order, a duplicate
subcircuit parameter) and one operator that disagreed with itself between two
evaluators.

WHAT IS DELIBERATELY NOT CHANGED, pinned here so a later round does not "fix"
it -- each was reported by the hunt and withdrawn on reading the code:
  * `vector(-4)` equals `vector(4)`: cx_vector's own comment documents "a
    vector from 0 to the MAGNITUDE of the argument", and the len==0 -> 1 clamp
    beside it is explicit. [W1]
  * `pulse` with a negative TR/TF/PW/PER: vsrcload.c documents "TR negative or
    0 --> TR = CKTstep", i.e. negative means "use the default". [W2]
  * `.dc v1 1 1 <step>` (start == stop) computing no rows: E-426 records that
    13 decks in examples/ depend on that form being accepted. [W3]
  * `ac lin 1`: span.c records that nine cards use `lin 1` as a legitimate
    single frequency. [W3]
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(body, ctl, tag, timeout=120):
    path = os.path.join(HERE, f"_gc_{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* gatecheck {tag}\n{body}\n.control\noption noacct\nset numdgt=12\n"
                f"{ctl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=timeout, cwd=HERE, stdin=subprocess.DEVNULL)
    try:
        os.remove(path)
    except OSError:
        pass
    return r.returncode, (r.stdout + r.stderr)


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


def rows(out):
    return [l.split() for l in out.splitlines() if re.match(r"^\d+\s+[-\d.]", l.strip())]


def said(out, pat):
    return bool(re.search(pat, out, re.I))


DIV = "V1 in 0 dc 1\nR1 in mid 1k\nR2 mid 0 1k"
TRI = "V1 a 0 pwl(0 0 1m 1 2m 0 3m 1 4m 0)\nR1 a 0 1k"

print("Enhancement-480: a check that could not fire where it mattered\n")

# ---------------------------------------------- 1. the duplicate-param gate --
print("a duplicate parameter is reported, and only when there is one")
rc, o = run(DIV.replace("R2 mid 0 1k", "R2 mid 0 rmod") + "\n.model rmod r(r=1k)",
            "op\nprint v(mid)", "dup_single")
check("[1] .model rmod r(r=1k) does NOT warn (the TYPE token is not a parameter)",
      not said(o, r"more than once|aliasparam"), "false positive")
check("[1] ...and still builds the 1k model", val(o, "v(mid)") == 0.5, f"v(mid)={val(o,'v(mid)')}")
rc, o = run(DIV.replace("R2 mid 0 1k", "R2 mid 0 rmod") + "\n.model rmod r(r=1k r=4k)",
            "op\nprint v(mid)", "dup_real")
check("[2] ...but a real duplicate still is, exactly once",
      len(re.findall(r"more than once", o, re.I)) == 1,
      f"{len(re.findall(r'more than once', o, re.I))} messages")
check("[2] ...and the last value wins", val(o, "v(mid)") == 0.8, f"v(mid)={val(o,'v(mid)')}")

# a device with ONE model parameter: the full-list gate used to hide the repeat
rc, o = run(DIV.replace("R2 mid 0 1k", "C2 mid 0 cmod") + "\n.model cmod c(c=1u c=2u)",
            "op\nprint v(mid)", "dup_one_parm")
check("[3] a repeat is found even when the device has ONE model parameter",
      said(o, r"more than once"), "the full-list gate hid it")

# ------------------------------------------------- 2. duplicate subckt param --
print("\na duplicate parameter on a subcircuit call")
rc, o = run("V1 in 0 dc 1\nRs in mid 1k\nX1 mid 0 s rv=4k rv=8k\n"
            ".subckt s n1 n2 rv=1k\nR1 n1 n2 {rv}\n.ends", "op\nprint v(mid)", "sub_dup")
check("[4] a duplicate subckt parameter is reported", said(o, r"more than once"), "silent")
check("[4] ...naming the value that wins", said(o, r"8k"), "")
rc, o = run("V1 in 0 dc 1\nRs in mid 1k\nX1 mid 0 s rv=4k\n"
            ".subckt s n1 n2 rv=1k\nR1 n1 n2 {rv}\n.ends", "op\nprint v(mid)", "sub_ok")
check("[5] a single one still passes quietly", not said(o, r"more than once"), "")

# ------------------------------------------------- 3. .measure edge counts ----
print("\n.measure edge counts cannot be mistaken for a sentinel")
rc, o = run(TRI, "tran 5u 4m\nmeas tran m when v(a)=0.5 fall=-1", "edge_neg")
check("[6] fall=-1 is refused, not answered with a RISING edge",
      said(o, r"not a valid edge count"), "answered anyway")
for spec, want, lbl in [("fall=1", 1.5e-3, "[7] fall=1 is the first falling edge"),
                        ("fall=2", 3.5e-3, "[7] fall=2 is the second"),
                        ("rise=1", 0.5e-3, "[8] rise=1 is the first rising edge"),
                        ("cross=2", 1.5e-3, "[8] cross=2 is the second crossing")]:
    rc, o = run(TRI, f"tran 5u 4m\nmeas tran m when v(a)=0.5 {spec}", "edge_" + re.sub(r"\W", "", spec))
    got = val(o, "m")
    check(lbl, got is not None and abs(got - want) < 2e-5, f"{spec} -> {got}")
rc, o = run(TRI, "tran 5u 4m\nmeas tran m when v(a)=0.5 cross=last", "edge_last")
check("[9] LAST still works (it is not a negative count)",
      val(o, "m") is not None and abs(val(o, "m") - 3.5e-3) < 2e-5, f"{val(o,'m')}")
rc, o = run(TRI, "tran 5u 4m\nmeas tran m when v(a)=0.5 cross=-2", "edge_neg2")
check("[9] ...while a written cross=-2 is refused rather than read as LAST",
      said(o, r"not a valid edge count"), "read as LAST")

# ------------------------------------------------------- 4. the % operator ----
print("\nthe % operator agrees with itself across evaluators")
for expr, want in [("(0.5) % 3", 0.5), ("(5.5) % 3", 2.5), ("(-5) % 3", -2.0),
                   ("(5.5) % (2.5)", 0.5), ("(5) % 3", 2.0)]:
    tag = re.sub(r"\W", "", expr)
    rc, o1 = run(f"V1 n 0 dc 0\nR1 n 0 1k\n.param p={{{expr}}}\nB1 pb 0 v={{p}}\nRb pb 0 1k",
                 "op\nprint v(pb)", "mp_" + tag)
    rc, o2 = run("V1 n 0 dc 0\nR1 n 0 1k", f"op\nlet z={expr}\nprint z", "ml_" + tag)
    a, c = val(o1, "v(pb)"), val(o2, "z")
    check(f"[10] {expr} is {want} in .param and in let",
          a is not None and c is not None and abs(a - want) < 1e-9 and abs(c - want) < 1e-9,
          f".param={a} let={c}")
rc, o = run("V1 n 0 dc 0\nR1 n 0 1k", "op\nlet z=(5) % 0\nprint z", "mod_zero")
check("[11] a zero divisor is still an error", val(o, "z") is None, "returned a value")

# ------------------------------------------------------ 5. the constant plot --
print("\nthe constant plot cannot be overwritten")
rc, o = run(DIV, "op\nlet i = 0\nwhile i < 3\n  let i = i + 1\nend\n"
                 "echo counted i=$&i\nsetplot const\nprint pi i", "const_i")
check("[12] a loop counter named `i` still works", said(o, r"counted i=3"), "")
check("[12] ...and const pi is untouched", abs((val(o, "pi") or 0) - 3.14159265358979) < 1e-9,
      f"pi={val(o,'pi')}")
# [13] The constant plot IS writable -- `let pi = 3` from within it redefines pi
# for the session, and `destroy const` is refused on the line before. That was
# found, and the fix was BUILT AND REVERTED: shadowing the write into the
# current plot protects the constant but leaves reads still resolving to the
# constant first, so the two paths disagree. `run` is itself a built-in
# constant, and examples/lhs_examples writes `let run = 0` and loops on it --
# with the shadow in place its `dowhile` never advanced and the suite hung.
# Making this safe means changing name resolution across the interpreter, which
# is far wider than the evidence. Pinned as it stands so the behaviour is at
# least recorded and a later attempt starts from here.
rc, o = run(DIV, "op\nsetplot const\nlet pi = 3\nprint pi", "const_pi")
check("[13] the constant plot is still writable -- KNOWN, fix reverted (see comment)",
      val(o, "pi") == 3.0, f"pi={val(o,'pi')} (3.0 is the unfixed behaviour)")

# ------------------------------------------------ 6. unterminated .control ----
print("\nan unterminated control block is reported")
rc, o = run(DIV, "op\nif 1\n  echo INSIDE\necho AFTER\nprint v(mid)", "blk_open")
check("[14] an `if` with no `end` is reported", said(o, r"not terminated"), "silent")
check("[14] ...exactly once, with no internal-error follow-on",
      len(re.findall(r"not terminated", o)) == 1 and not said(o, r"Internal Error"),
      f"{len(re.findall(r'not terminated', o))} messages")
rc, o = run(DIV, "op\nif 1\n  echo INSIDE\nend\necho AFTER\nprint v(mid)", "blk_closed")
check("[15] a terminated block still runs",
      said(o, r"INSIDE") and said(o, r"AFTER") and val(o, "v(mid)") == 0.5, "")

# ------------------------------------------------- 7. transmission line -------
print("\na transmission line's delay is formed from usable numbers")
TL = "V1 in 0 ac 1 dc 0\nR1 in a 50\n"
rc, o = run(TL + "T1 a 0 b 0 z0=50 f=0 nl=0.25\nRl b 0 50",
            "ac dec 1 1meg 10meg\nprint mag(v(b))", "tl_f0")
check("[16] f=0 is refused instead of reporting nan",
      said(o, r"no wavelength"), "nan reported as a result")
check("[16] ...and no nan row is printed",
      not any("nan" in r[2].lower() for r in rows(o)), "")
for spec, lbl in [("z0=-50 td=1n", "[17] a negative z0 is refused"),
                  ("z0=50 td=-1n", "[17] a negative td is refused"),
                  ("z0=0 td=1n", "[17] a zero z0 is refused")]:
    rc, o = run(TL + f"T1 a 0 b 0 {spec}\nRl b 0 50", "ac dec 1 1meg 10meg\nprint mag(v(b))",
                "tl_" + re.sub(r"\W", "", spec))
    check(lbl, said(o, r"not a usable"), "accepted")
rc, o = run(TL + "T1 a 0 b 0 z0=50 td=1n\nRl b 0 50", "ac dec 1 1meg 10meg\nprint mag(v(b))", "tl_ok")
g = [float(r[2]) for r in rows(o)]
check("[18] a valid line still works", bool(g) and abs(g[0] - 0.5) < 1e-6, f"gain={g[:1]}")

# ------------------------------------------------------ 8. switch hysteresis --
print("\na switch's hysteresis joins ron/roff in the physics check")
SW = "Vctl ctl 0 dc 1\nV1 in 0 dc 1\nS1 in out ctl 0 sw\nRl out 0 1k\n"
rc, o = run(SW + ".model sw sw(vt=0.5 vh=-0.1 ron=1 roff=1e9)\n.option warn_physics",
            "op\nprint v(out)", "sw_vh")
check("[19] a negative vh is reported under warn_physics", said(o, r"hysteresis"), "silent")
rc, o = run(SW + ".model sw sw(vt=0.5 vh=0.1 ron=1 roff=1e9)\n.option warn_physics",
            "op\nprint v(out)", "sw_ok")
check("[19] ...and a normal one is not", not said(o, r"hysteresis"), "false positive")

# ------------------------------------------------------- 9. XSPICE models ----
print("\nXSPICE code-model parameter faults are reported once, in every analysis")
LIM = ("V1 in 0 sin(0 1 1k)\nR1 in 0 1k\nA1 in out l1\n"
       ".model l1 limit(in_offset=0 gain=1 out_lower_limit=5 out_upper_limit=-5)\nRo out 0 1k")
for an, lbl in [("op", "[20] limiter: reversed limits reported in op"),
                ("dc v1 -8 8 4", "[20] ...in dc"),
                ("tran 10u 1m", "[20] ...and in tran")]:
    rc, o = run(LIM, an, "lim_" + re.sub(r"\W", "", an)[:8])
    n = len(re.findall(r"out_upper_limit is below", o))
    check(lbl + " -- exactly once", n == 1, f"{n} messages")
rc, o = run("V1 in 0 dc 1\nR1 in 0 1k\nA1 in out p1\n"
            ".model p1 pwl(x_array=[0 2 1] y_array=[0 2 4])\nRo out 0 1k",
            "op\nprint v(out)", "pwl_nm")
check("[21] a non-monotonic pwl x_array is reported", said(o, r"monotonic"), "silent")
rc, o = run("V1 in 0 dc 1\nR1 in 0 1k\nA1 in out p1\n"
            ".model p1 pwl(x_array=[0 1 2] y_array=[0 2 4])\nRo out 0 1k",
            "op\nprint v(out)", "pwl_ok")
check("[21] ...and an ascending one is not", not said(o, r"monotonic"),
      f"v(out)={val(o,'v(out)')}")

# ---------------------------------------------------------- 10. .dc span -----
print("\na .dc step larger than its span")
rc, o = run(DIV, "dc v1 0 0.1 1\nprint v(mid)", "dc_span")
check("[22] a step larger than the span is reported", said(o, r"larger than the span"), "silent")
rc, o = run(DIV, "dc v1 0 1 0.25\nprint v(mid)", "dc_ok")
check("[22] ...and a normal sweep is not", not said(o, r"larger than the span")
      and len(rows(o)) == 5, f"rows={len(rows(o))}")
rc, o = run(DIV, "dc v1 2 0 -0.5\nprint v(mid)", "dc_desc")
check("[22] ...nor a descending one", not said(o, r"larger than the span")
      and len(rows(o)) == 5, f"rows={len(rows(o))}")

# ------------------------------------- 11. pinned decisions, NOT to be fixed --
print("\ndeliberately unchanged (pinned so a later round does not 'fix' them)")
rc, o = run(DIV, "op\nlet a=vector(-4)\nlet b=vector(4)\nprint length(a) length(b)", "w_vec")
check("[W1] vector(-4) still equals vector(4) -- cx_vector documents the MAGNITUDE",
      val(o, "length(a)") == 4.0 and val(o, "length(b)") == 4.0,
      f"{val(o,'length(a)')}/{val(o,'length(b)')}")
rc, o = run("V1 a 0 pulse(0 1 0 -100u 1u 400u 2m)\nR1 a 0 1k",
            "tran 5u 1m\nmeas tran v50 find v(a) at=50u", "w_pulse")
check("[W2] a negative pulse TR still means 'use the default' (vsrcload documents it)",
      val(o, "v50") is not None and val(o, "v50") > 0.99, f"v(50u)={val(o,'v50')}")
rc, o = run(DIV, "dc v1 1 1 0.25\nprint v(mid)", "w_startstop")
check("[W3] .dc with start == stop is still accepted -- E-426: 13 decks rely on it",
      rc == 0 and not said(o, r"larger than the span"), "")
rc, o = run("V1 in 0 dc 1 ac 1\nR1 in mid 1k\nC1 mid 0 1u\nR2 mid 0 1k",
            "ac lin 1 1meg 1meg\nprint v(mid)", "w_aclin1")
check("[W3] ...and `ac lin 1` is still accepted -- span.c: nine cards use it", rc == 0, f"rc={rc}")

print(f"\n=== {passed}/{checks} checks passed ===")
sys.exit(0 if passed == checks else 1)
