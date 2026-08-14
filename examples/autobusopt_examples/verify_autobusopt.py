#!/usr/bin/env python3
"""Enhancement-454: `.option autobus` meant different things in different places.

TWO READERS decide whether autobus is on, and they disagreed.

  * The SUBCIRCUIT path (Enhancement-449) reads the option cards directly,
    because the option variable is not published until after expansion. It used
    a `strstr` with only a token-boundary test -- enough to ignore `noautobus`
    and `myautobus`, but it accepted `=` as a mere terminator and NEVER LOOKED
    AT THE VALUE. So `.option autobus=0`, `=false` and `=no` all switched the
    feature ON, silently. Enhancement-450 had already fixed exactly this for
    `savecurrents`; autobus was its unguarded sibling.

  * The TOP-LEVEL path (Enhancement-444, in INP2N) reads the published variable
    with `cp_getvar(.., CP_BOOL, ..)`. But the spelling decides the type: bare
    `.option autobus` publishes a BOOL, `autobus=1` a NUMBER, `autobus=true` a
    STRING. Only the bare form was ever seen, so `.option autobus=1` -- an
    ordinary way to write a boolean option, and NOT reported as unknown -- left
    a top-level bus port unbound.

Together those two point in opposite directions, so the same card meant ON in a
subcircuit and off at the top level, or the reverse. That is what this suite
pins: not merely that each spelling is right, but that BOTH PATHS AGREE.

Also here: a bus could be bound by name at the level that DECLARED it, but not
passed down. `Xi a b inner`, for `.subckt inner a[0:4] b`, failed with "too few
nodes" -- the expansion was allowed on an OSDI device line only. The two spend
their node budget differently (an OSDI line's budget is the tokens written, a
subcircuit call's is the callee's formal count), which is why one token standing
for five nodes has to be counted differently in each.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = passed = 0
# Everything generated goes to the system temp directory: this script is
# re-executed once per solver by check_both_solvers, so a cleanup at the end
# of the file never runs in the parent -- and artifacts were left behind in
# the example directory.
WORK = tempfile.gettempdir()
OSDI = os.path.join(WORK, "_ab.osdi")
# five sources, each through 1k into its own node
SRC = "\n".join(f"V{i} s{i} 0 dc {i+1}\nR{i} s{i} n{i} 1k" for i in range(5))


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(deck, tag, names=None):
    """Run one deck; return the five probed node voltages and the raw output.

    `names` are the vector names to read. The two paths probe DIFFERENT nodes:
    inside a subcircuit the bus is bound to the caller's n0..n4, while at the top
    level a short line binds the bus's own a[0]..a[4]. Probing n0..n4 in the
    top-level deck made "on" and "off" look identical -- both leave those nodes
    unloaded -- and the check passed while measuring nothing.
    """
    if names is None:
        names = [f"n{i}" for i in range(5)]
    p = os.path.join(WORK, f"_ab_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True,
                       timeout=300, stdin=subprocess.DEVNULL, cwd=HERE)
    out = r.stdout + r.stderr
    return [(lambda m: float(m.group(1)) if m else None)(
                re.search(rf"v\({re.escape(nm)}\)\s*=\s*(-?[\d.eE+-]+)", out))
            for nm in names], out


TOP_NAMES = [f"a[{i}]" for i in range(5)]


def sub_deck(opt):
    """the device sits INSIDE a subcircuit -- Enhancement-449's path"""
    return f"""* autobus in a subcircuit
{opt}
{SRC}
.subckt mysub a[0:4] b
N1 a b autobusopt
.model autobusopt autobusopt()
.ends mysub
X1 n0 n1 n2 n3 n4 b mysub
Vb b 0 dc 0
.control
pre_osdi {OSDI}
op
print v(n0) v(n1) v(n2) v(n3) v(n4)
.endc
.end
"""


def top_deck(opt):
    """the device sits at the TOP level -- Enhancement-444's path.

    The sources drive a[0]..a[4] by name, so the short line `N1 a b` binds the
    very nodes being probed: with autobus on they are loaded by the model, with
    it off they float at their source values.
    """
    src = "\n".join(f"V{i} s{i} 0 dc {i+1}\nR{i} s{i} a[{i}] 1k" for i in range(5))
    return f"""* autobus at the top level
{opt}
{src}
N1 a b autobusopt
.model autobusopt autobusopt()
Vb b 0 dc 0
.control
pre_osdi {OSDI}
op
print v(a[0]) v(a[1]) v(a[2]) v(a[3]) v(a[4])
.endc
.end
"""


print("Enhancement-454: one option, one meaning\n")
r = subprocess.run([OPENVAF, os.path.join(HERE, "autobusopt.va"), "-o", OSDI],
                   capture_output=True, text=True, timeout=600, cwd=HERE)
check("[E-454] the Verilog-A model compiles", r.returncode == 0 and os.path.isfile(OSDI),
      (r.stdout + r.stderr).strip().splitlines()[0][:60] if r.returncode else "")

# The two reference states each path can be in. Both decks are built so that
# "bound" and "unbound" carry DIFFERENT voltages -- a deck where the two states
# read the same would let every spelling check below pass while measuring
# nothing, which is exactly what an earlier version of this file did.
SUB_ON, _ = run(sub_deck(".option autobus"), "subon")
SUB_OFF, _ = run(sub_deck(""), "suboff")
TOP_ON, _ = run(top_deck(".option autobus"), "topon", TOP_NAMES)
TOP_OFF, _ = run(top_deck(""), "topoff", TOP_NAMES)
check("[E-454] the subcircuit path distinguishes on from off", SUB_ON != SUB_OFF,
      f"{SUB_ON} vs {SUB_OFF}")
check("[E-454] the top-level path distinguishes on from off", TOP_ON != TOP_OFF,
      f"{TOP_ON} vs {TOP_OFF}")


def state(got, on, off):
    return "ON" if got == on else ("off" if got == off else "?")


print("\nevery spelling means the same thing on BOTH paths")
SPELLINGS = [
    (".option autobus", "ON"),
    (".option autobus=1", "ON"),
    (".option autobus=true", "ON"),
    (".option autobus=yes", "ON"),
    (".option autobus=on", "ON"),
    (".option autobus=0", "off"),
    (".option autobus=false", "off"),
    (".option autobus=no", "off"),
    (".option autobus=off", "off"),
    (".option noautobus", "off"),
    (".option myautobus", "off"),
    (".option xautobus=1", "off"),
    (".option autobusx", "off"),
    ("", "off"),
]
for opt, want in SPELLINGS:
    tag = re.sub(r"\W", "", opt)[-10:] or "none"
    s_got, _ = run(sub_deck(opt), "s" + tag)
    t_got, _ = run(top_deck(opt), "t" + tag, TOP_NAMES)
    s, t = state(s_got, SUB_ON, SUB_OFF), state(t_got, TOP_ON, TOP_OFF)
    label = opt if opt else "(no option at all)"
    check(f"[E-454] {label:22s} -> {want} on both paths",
          s == want and t == want, f"subckt={s} toplevel={t}")

print("\nprecedence, and it is the same on both paths")
# Within one card the later token wins; ACROSS cards the options machinery keeps
# the first, and the card reader must not contradict it -- making the reader
# "last card wins" would put the two paths back into disagreement.
for opt, want, note in [
    (".option autobus=0 autobus", "ON", "later token on one card wins"),
    (".option autobus autobus=0", "off", "later token on one card wins"),
    (".option autobus\n.option autobus=0", "ON", "first card wins, as the option machinery does"),
    (".option autobus=0\n.option autobus", "off", "first card wins, as the option machinery does"),
]:
    tag = re.sub(r"\W", "", opt)[-11:]
    s_got, _ = run(sub_deck(opt), "p" + tag)
    t_got, _ = run(top_deck(opt), "q" + tag, TOP_NAMES)
    s, t = state(s_got, SUB_ON, SUB_OFF), state(t_got, TOP_ON, TOP_OFF)
    check(f"[E-454] {note}", s == want and t == want, f"subckt={s} toplevel={t}, wanted {want}")

print("\na bus port can be passed DOWN through subcircuits")
REF, _ = run(f"""* explicit reference
{SRC}
N1 n0 n1 n2 n3 n4 b autobusopt
.model autobusopt autobusopt()
Vb b 0 dc 0
.control
pre_osdi {OSDI}
op
print v(n0) v(n1) v(n2) v(n3) v(n4)
.endc
.end
""", "ref")
INNER = (".subckt inner a[0:4] b\nN1 a b autobusopt\n"
         ".model autobusopt autobusopt()\n.ends inner\n")


def nest(body, tag, opt=".option autobus"):
    return run(f"""* nested autobus
{opt}
{SRC}
{body}
Vb b 0 dc 0
.control
pre_osdi {OSDI}
op
print v(n0) v(n1) v(n2) v(n3) v(n4)
.endc
.end
""", tag)


for label, body in [
    ("one level (the device line)", INNER + "X1 n0 n1 n2 n3 n4 b inner"),
    ("two levels (a short X call)",
     INNER + ".subckt outer a[0:4] b\nXi a b inner\n.ends outer\nX1 n0 n1 n2 n3 n4 b outer"),
    ("three levels",
     INNER + ".subckt mid a[0:4] b\nXi a b inner\n.ends mid\n"
     ".subckt outer a[0:4] b\nXm a b mid\n.ends outer\nX1 n0 n1 n2 n3 n4 b outer"),
    ("two levels, inner call spelled out",
     INNER + ".subckt outer a[0:4] b\nXi a[0] a[1] a[2] a[3] a[4] b inner\n.ends outer\n"
     "X1 n0 n1 n2 n3 n4 b outer"),
]:
    got, _ = nest(body, "n" + re.sub(r"\W", "", label)[:9])
    check(f"[E-454] {label} binds the bus correctly", got == REF, f"{got} vs {REF}")

# Without the option an X line must behave exactly as it always did.
got, out = nest(INNER + ".subckt outer a[0:4] b\nXi a b inner\n.ends outer\n"
                "X1 n0 n1 n2 n3 n4 b outer", "nooptx", opt="")
check("[E-454] with the option OFF a short X call is still the old clean error",
      "too few nodes" in out, out.strip().splitlines()[0][:60] if out.strip() else "")
check("[E-454] ...and it does not crash", "Segmentation" not in out and "Abort" not in out)

for junk in os.listdir(WORK):
    if junk.startswith("_ab"):
        try:
            os.remove(os.path.join(WORK, junk))
        except OSError:
            pass

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
