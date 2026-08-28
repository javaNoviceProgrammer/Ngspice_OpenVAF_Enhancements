#!/usr/bin/env python3
"""Enhancement-500: `pre_osdi -va` compiles Verilog-A and loads it in one step.

A deck that ships its own models needed a separate build before it could run:
compile each `.va` by hand, then point `pre_osdi` at the objects. `pre_osdi -va
model.va` does both -- it invokes openvaf-r and loads what comes out.

WHERE THE OBJECTS GO. Into an `osdi/` directory beside the NETLIST, not beside
the working directory and not next to each source. That keeps a model directory
clean, and it makes an input/output collision structurally impossible:
Enhancement-452 recorded `openvaf-r m.va -o m.va` DESTROYING the source and
exiting 0. The `.va` argument itself is resolved against the netlist too, the way
load_osdi() already resolves the object it is given -- the two halves of one
command must not disagree about what a relative path means.

WHICH COMPILER. osdi_find_openvaf(), shared with `pre_snp` rather than
reimplemented: the `openvaf` ngspice variable, then $OPENVAF, then
$SPICE_LIB_DIR/openvaf-r, then PATH. A bare PATH search would miss the compiler
shipped in the bundle, which is exactly where it lives for most users.

RECOMPILING IS THE DEFAULT; `.option osdicache` opts out. The usual instinct is
the other way round, and it is wrong while openvaf-r itself is under development:
a `.va` timestamp says only whether the SOURCE changed, and a skipped rebuild
then loads an object built by a compiler that no longer exists. That is the shape
of Enhancement-453, whose cache key omitted its own codegen settings. `-f`
bypasses the cache outright, because Enhancement-229 added that flag for the
edit -> recompile -> re-source loop and under `-va` the compile is part of it.

The staleness test is STRICTLY newer, never `>=`: st_mtime is one-second granular
on POSIX and two-second on FAT, so a tie must rebuild. A tie costs one needless
compile; the other way costs a wrong answer.
"""
import atexit
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

WORK = os.path.join(HERE, "_va_work")


def _cleanup():
    shutil.rmtree(WORK, ignore_errors=True)
    for junk in os.listdir(HERE):
        if junk.startswith("_va_"):
            p = os.path.join(HERE, junk)
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def fresh():
    """a clean working directory holding the two models.

    The sources are stamped an hour in the past on purpose. A freshly copied
    `.va` would otherwise carry the current time, the object compiled a moment
    later would land in the SAME one-second st_mtime bucket, and the deliberately
    conservative tie rule (a tie rebuilds) would fire -- masking whether the
    cache works at all. Stamping them models the real case: a source edited some
    time ago and an object built now."""
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    for m in ("rmod.va", "gmod.va", "bad.va"):
        dst = os.path.join(WORK, m)
        shutil.copy(os.path.join(HERE, m), dst)
        os.utime(dst, (1_700_000_000, 1_700_000_000))


# The deck pins the compiler explicitly so the suite tests THIS tree's openvaf-r
# rather than whatever a developer happens to have on PATH.
PIN = f"set openvaf={OPENVAF}\n"

DIVIDER = ("V1 a 0 dc 1\n"
           "N1 a n mm\n"
           ".model mm rmod r0=1k\n"
           "N2 n 0 gm\n"
           ".model gm gmod g0=1m\n")
RONLY = ("V1 a 0 dc 1\n"
         "N1 a n mm\n"
         ".model mm rmod r0=1k\n"
         "R2 n 0 1k\n")
TAIL = (".control\noption noacct\nset numdgt=10\nop\nprint v(n)\n.endc\n.end\n")


def deck(name, pre, body=RONLY, opts=""):
    p = os.path.join(WORK, name)
    with open(p, "w") as f:
        f.write(f"vacompile\n{opts}.control\n{PIN}{pre}\n.endc\n{body}{TAIL}")
    return p


def run(path, cwd=None):
    r = subprocess.run([NGSPICE, "-b", os.path.relpath(path, cwd or WORK)],
                       cwd=cwd or WORK, capture_output=True, text=True,
                       timeout=900, errors="replace")
    return r.returncode, r.stdout + r.stderr


def vn(out):
    m = re.search(r"^v\(n\)\s*=\s*(\S+)", out, re.M)
    return m.group(1) if m else None


def built(out):
    """'built' if the compiler ran, 'cached' if it was skipped, else None"""
    if "up to date" in out:
        return "cached"
    if re.search(r"pre_osdi: .* -> ", out):
        return "built"
    return None


def touch(path, stamp):
    os.utime(path, (stamp, stamp))


print("Enhancement-500: pre_osdi -va compiles Verilog-A and loads it\n")

# ------------------------------------------------------ compile and load ----
print("compile, load, and put the objects where they belong")

fresh()
d = deck("run.cir", "pre_osdi -va rmod.va")
rc, o = run(d)
check("[1] a .va is compiled and the object it produces is loaded",
      rc == 0 and vn(o) == "5.0000000000e-01", f"rc={rc} v(n)={vn(o)}")
check("[2] the object lands in osdi/ beside the netlist",
      os.path.isfile(os.path.join(WORK, "osdi", "rmod.osdi")),
      str(sorted(os.listdir(WORK))))

# run from the PARENT directory: the netlist, not the cwd, anchors everything
fresh()
d = deck("run.cir", "pre_osdi -va rmod.va")
rc, o = run(d, cwd=HERE)
check("[3] run from another directory: the .va still resolves, against the netlist",
      rc == 0 and vn(o) == "5.0000000000e-01", f"rc={rc} v(n)={vn(o)}")
check("[4] ...and osdi/ is beside the NETLIST, not the working directory",
      os.path.isfile(os.path.join(WORK, "osdi", "rmod.osdi")) and
      not os.path.isdir(os.path.join(HERE, "osdi")))

fresh()
d = deck("run.cir", f"pre_osdi -va {os.path.join(WORK, 'rmod.va')}")
rc, o = run(d, cwd=HERE)
check("[5] an absolute .va path works too", rc == 0 and vn(o) == "5.0000000000e-01",
      f"v(n)={vn(o)}")

fresh()
d = deck("two.cir", "pre_osdi -va rmod.va gmod.va", body=DIVIDER)
rc, o = run(d)
check("[6] two .va files in one command", rc == 0 and vn(o) == "5.0000000000e-01",
      f"v(n)={vn(o)}")
check("[7] ...both objects are collected in osdi/",
      sorted(os.listdir(os.path.join(WORK, "osdi"))) == ["gmod.osdi", "rmod.osdi"],
      str(sorted(os.listdir(os.path.join(WORK, "osdi")))))

# ---------------------------------------------------------- the default ----
# Recompiling every run is the default ON PURPOSE: see the module docstring.
print("\nrecompiling is the default")

fresh()
d = deck("run.cir", "pre_osdi -va rmod.va")
seen = [built(run(d)[1]) for _ in range(3)]
check("[8] every run recompiles when the deck says nothing", seen == ["built"] * 3,
      str(seen))

# ------------------------------------------------------ .option osdicache ----
print("\n.option osdicache opts into skipping an up-to-date object")

fresh()
d = deck("run.cir", "pre_osdi -va rmod.va", opts=".option osdicache\n")
seen = [built(run(d)[1]) for _ in range(3)]
check("[9] the first run builds and later runs skip", seen == ["built", "cached", "cached"],
      str(seen))

osdi = os.path.join(WORK, "osdi", "rmod.osdi")
va = os.path.join(WORK, "rmod.va")

touch(osdi, 1_700_000_000)
touch(va, 1_700_003_600)                       # source an hour newer
check("[10] a newer .va rebuilds", built(run(d)[1]) == "built")

touch(osdi, 1_700_007_200)                     # object newer again
check("[11] an older .va is skipped", built(run(d)[1]) == "cached")

touch(osdi, 1_700_000_000)
touch(va, 1_700_000_000)                       # SAME timestamp
check("[12] an identical timestamp rebuilds -- st_mtime is coarse, so a tie "
      "must not be read as up to date", built(run(d)[1]) == "built")

os.remove(osdi)
check("[13] a missing object rebuilds", built(run(d)[1]) == "built")

for spell in ("osdicache=0", "osdicache=false", "osdicache=no", "osdicache=off"):
    fresh()
    d2 = deck("run.cir", "pre_osdi -va rmod.va", opts=f".option {spell}\n")
    seen = [built(run(d2)[1]) for _ in range(2)]
    check(f"[14-{spell}] every spelling that means off means off",
          seen == ["built", "built"], str(seen))

fresh()
d2 = deck("run.cir", "pre_osdi -va rmod.va", opts=".options klu osdicache\n")
seen = [built(run(d2)[1]) for _ in range(2)]
check("[15] `.options` (plural), alongside another option, still enables it",
      seen == ["built", "cached"], str(seen))

# ----------------------------------------------------------------- -f ----
print("\n-f forces the rebuild, not just the reload")

fresh()
d = deck("run.cir", "pre_osdi -va rmod.va", opts=".option osdicache\n")
run(d)
osdi = os.path.join(WORK, "osdi", "rmod.osdi")
touch(osdi, 1_700_007_200)
touch(os.path.join(WORK, "rmod.va"), 1_700_000_000)
check("[16] (control) without -f an up-to-date object is skipped",
      built(run(d)[1]) == "cached")

for pre in ("pre_osdi -f -va rmod.va", "pre_osdi -va -f rmod.va"):
    df = deck("f.cir", pre, opts=".option osdicache\n")
    touch(osdi, 1_700_007_200)
    check(f"[17] `{pre}` rebuilds despite the cache", built(run(df)[1]) == "built")

# the reason the flag has to reach the compile: an edit must be picked up
fresh()
d = deck("run.cir", "pre_osdi -va gmod.va", opts=".option osdicache\n",
         body="V1 a 0 dc 1\nR1 a n 1k\nN2 n 0 gm\n.model gm gmod g0=1m\n")
rc, o = run(d)
first = vn(o)
src = os.path.join(WORK, "gmod.va")
with open(src) as f:
    txt = f.read()
with open(src, "w") as f:
    f.write(txt.replace("g0 * V(a,b)", "2.0 * g0 * V(a,b)"))
touch(os.path.join(WORK, "osdi", "gmod.osdi"), 1_700_007_200)
touch(src, 1_700_000_000)                      # object looks up to date
stale = vn(run(d)[1])
df = deck("f.cir", "pre_osdi -f -va gmod.va", opts=".option osdicache\n",
          body="V1 a 0 dc 1\nR1 a n 1k\nN2 n 0 gm\n.model gm gmod g0=1m\n")
touch(os.path.join(WORK, "osdi", "gmod.osdi"), 1_700_007_200)
fixed = vn(run(df)[1])
check("[18] an EDITED .va is picked up by -f and not without it",
      first == "5.0000000000e-01" and stale == first and
      fixed == "3.3333333333e-01", f"first={first} stale={stale} -f={fixed}")

# ------------------------------------------------------------- mixing ----
# -va only changes how a .va ARGUMENT becomes a path; anything else still goes
# straight to load_osdi, so the two mechanisms converge on one loader.
print("\nmixing -va with plain pre_osdi")

def prebuild():
    """compile gmod by hand, as a user would have done before this existed"""
    out = os.path.join(WORK, "prebuilt")
    os.makedirs(out, exist_ok=True)
    subprocess.run([OPENVAF, "gmod.va", "-o", os.path.join(out, "gmod.osdi")],
                   cwd=WORK, capture_output=True, text=True, timeout=900)
    return os.path.isfile(os.path.join(out, "gmod.osdi"))


MIXES = [
    ("two lines, -va first", "pre_osdi -va rmod.va\npre_osdi prebuilt/gmod.osdi"),
    ("two lines, plain first", "pre_osdi prebuilt/gmod.osdi\npre_osdi -va rmod.va"),
    ("one line, -va then .osdi", "pre_osdi -va rmod.va prebuilt/gmod.osdi"),
    ("one line, .osdi then -va", "pre_osdi prebuilt/gmod.osdi -va rmod.va"),
    ("one line, -f -va and .osdi", "pre_osdi -f -va rmod.va prebuilt/gmod.osdi"),
]
for nm, pre in MIXES:
    fresh()
    ok = prebuild()
    d = deck("mix.cir", pre, body=DIVIDER)
    rc, o = run(d)
    check(f"[19-{nm}] a compiled model and a pre-built one work in one deck",
          ok and rc == 0 and vn(o) == "5.0000000000e-01", f"rc={rc} v(n)={vn(o)}")

fresh()
prebuild()
d = deck("dup.cir", "pre_osdi -va gmod.va\npre_osdi prebuilt/gmod.osdi",
         body="V1 a 0 dc 1\nR1 a n 1k\nN2 n 0 gm\n.model gm gmod g0=1m\n")
rc, o = run(d)
check("[20] the same model arriving by BOTH routes is not an error",
      rc == 0 and vn(o) == "5.0000000000e-01", f"rc={rc} v(n)={vn(o)}")

# ------------------------------------------------------------ refusals ----
print("\nwhat it says when it cannot do the job")

fresh()
d = deck("miss.cir", "pre_osdi -va nosuch.va", body="V1 a 0 dc 1\nR1 a 0 1k\n")
rc, o = run(d)
check("[21] a .va that does not exist is named, not reported as an exit status",
      "no such Verilog-A source" in o, o.strip().splitlines()[-1][:60])

fresh()
d = deck("bad.cir", "pre_osdi -va bad.va", body="V1 a 0 dc 1\nR1 a 0 1k\n")
rc, o = run(d)
check("[22] a .va that does not compile reports the compiler's own errors",
      "openvaf-r failed" in o and "error" in o.lower(),
      o.strip().splitlines()[-1][:60])
check("[23] ...and points at every way to supply the compiler",
      "set openvaf=" in o and "OPENVAF" in o and "SPICE_LIB_DIR" in o)

# ------------------------------------------------------------ controls ----
print("\ncontrols -- what must not change")

fresh()
prebuild()
d = deck("plain.cir", "pre_osdi prebuilt/gmod.osdi",
         body="V1 a 0 dc 1\nR1 a n 1k\nN2 n 0 gm\n.model gm gmod g0=1m\n")
rc, o = run(d)
check("[24] (control) plain `pre_osdi file.osdi` is unchanged",
      rc == 0 and vn(o) == "5.0000000000e-01", f"rc={rc} v(n)={vn(o)}")

fresh()
d = deck("nova.cir", "pre_osdi -va prebuilt/gmod.osdi",
         body="V1 a 0 dc 1\nR1 a 0 1k\n")
prebuild()
rc, o = run(d)
check("[25] (control) -va on a line with no .va argument is a no-op, not an error",
      "no such Verilog-A source" not in o)

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
