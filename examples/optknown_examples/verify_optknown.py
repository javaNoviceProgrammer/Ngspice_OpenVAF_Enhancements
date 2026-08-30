#!/usr/bin/env python3
"""Enhancement-511: an option the run honours, reported as unknown.

`.option osdicache` printed

    Warning: unknown option 'osdicache' on a .options card; ignored.

and then cached the compile anyway -- the run said it was ignoring a setting it
had already acted on. User-reported.

TWO ENHANCEMENTS COLLIDING. Enhancement-500 reads `osdicache` straight off the
option cards in `inp.c`, deliberately NOT through `cp_getvar`: `pre_osdi -va` runs
before any option has been published, so cp_getvar would answer for the previous
deck (the trap Enhancement-464 recorded for `autobus`). Enhancement-438 later made
an unrecognised name on a `.options` card a warning, because a misspelling used to
be silently inert -- `.options reltoll=1e-12` left reltol at its default while the
user believed the tolerance had been tightened. `osdicache` never reaches the
simulator option table at all, so E-438's check calls it unknown.

That is exactly the failure the allow-list in `spiceif.c` exists to prevent, and
its own comment says so:

    a warning that fires on a setting the run then honours is worse than no
    warning: it teaches the user to ignore the check E-438 added.

`autobus`, `saveused`, `klu`, `reusesetup` and `noinit` are all listed there.
`osdicache` was simply never added -- and `seedinfo` had the identical defect:
read from the deck at `inp.c` and acted on by `setseedinfo()`, which makes
`randnumb.c` print the seed it chose, yet reported unknown.

THE CHECK MUST STILL BITE. A genuine misspelling has to keep warning, or the fix
would undo E-438. Checks [4] and [5] hold that line, [5] with E-438's own
`reltoll` example.

NOT A DEFECT, worth knowing: if a `.va` and its `.osdi` are written within the
SAME SECOND the cache is skipped and the model rebuilds. That is deliberate --
`st_mtime` has one-second granularity, so the test is STRICTLY newer; a tie costs
one needless recompile, the other way loads the object built from the previous
text. Check [8] pins the cache hit after that window.
"""

import atexit
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)

WORK = os.path.join(HERE, "_ok_work")


def _cleanup():
    shutil.rmtree(WORK, ignore_errors=True)


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(deck, tag, timeout=180):
    os.makedirs(WORK, exist_ok=True)
    p = os.path.join(WORK, f"{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=WORK,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return None, "[TIMEOUT]"


def warned(out, name):
    return f"unknown option '{name}'" in out


print("Enhancement-511: an option the run honours, reported as unknown")

# ---------------------------------------------------------------------------
# 1. the two front-end options are no longer called unknown
# ---------------------------------------------------------------------------
print("\n  an option the run honours is not reported unknown")

PLAIN = ("* optknown\nV1 a 0 dc 1\nR1 a 0 1k\n{card}\n"
         ".control\noption noacct\nop\nprint v(a)\n.endc\n.end\n")

for i, (card, name) in enumerate([(".option osdicache", "osdicache"),
                                  (".option osdicache=0", "osdicache"),
                                  (".option seedinfo", "seedinfo")]):
    rc, out = run(PLAIN.format(card=card), f"ok{i}")
    check(f"`{card}` is accepted", not warned(out, name),
          [l.strip() for l in out.splitlines() if "unknown option" in l][:1])

# ---------------------------------------------------------------------------
# 2. E-438's check still bites
# ---------------------------------------------------------------------------
print("\n  a genuine misspelling still warns -- E-438's check is intact")

rc, out = run(PLAIN.format(card=".option osdicaches"), "bad1")
check("a misspelt `osdicaches` is still reported", warned(out, "osdicaches"))
rc, out = run(PLAIN.format(card=".option reltoll=1e-12"), "bad2")
check("E-438's own `reltoll` example is still reported", warned(out, "reltoll"))

# ---------------------------------------------------------------------------
# 3. the option it was warning about actually works
# ---------------------------------------------------------------------------
print("\n  and the setting it warned about does what it says")

os.makedirs(WORK, exist_ok=True)
shutil.copy(os.path.join(HERE, "cachemod.va"), os.path.join(WORK, "cachemod.va"))
# keep the source strictly older than any object built from it (one-second mtime)
os.utime(os.path.join(WORK, "cachemod.va"), (time.time() - 5, time.time() - 5))

VA = ("* optknown cache\nV1 a 0 dc 1\nN1 a 0 mm\n.model mm cachemod r=1000\n{card}\n"
      ".control\npre_osdi -va cachemod.va\noption noacct\nop\nprint i(v1)\n.endc\n.end\n")

shutil.rmtree(os.path.join(WORK, "osdi"), ignore_errors=True)
rc, first = run(VA.format(card=".option osdicache"), "c1")
check("the first run compiles the Verilog-A", "Finished building" in first or "pre_osdi:" in first,
      first.strip()[-120:] if "pre_osdi" not in first else "")
check("  ... and the model solves (i(v1) = -1e-03)", "-1.00000e-03" in first,
      [l.strip() for l in first.splitlines() if "i(v1)" in l][:1])

rc, second = run(VA.format(card=".option osdicache"), "c1")
check("the second run reuses the object", "is up to date" in second,
      [l.strip() for l in second.splitlines() if "pre_osdi" in l][:1])
check("  ... without warning about the option that made it do so",
      not warned(second, "osdicache"))

shutil.rmtree(os.path.join(WORK, "osdi"), ignore_errors=True)
rc, d1 = run(VA.format(card=""), "c2")
rc, d2 = run(VA.format(card=""), "c2")
check("without the option the default is to REBUILD", "is up to date" not in d2,
      [l.strip() for l in d2.splitlines() if "pre_osdi" in l][:1])

shutil.rmtree(os.path.join(WORK, "osdi"), ignore_errors=True)
rc, o1 = run(VA.format(card=".option osdicache=0"), "c3")
rc, o2 = run(VA.format(card=".option osdicache=0"), "c3")
check("`osdicache=0` means off, and is still not reported unknown",
      "is up to date" not in o2 and not warned(o2, "osdicache"))

# ---------------------------------------------------------------------------
# 4. seedinfo, the other one, also still does its job
# ---------------------------------------------------------------------------
print("\n  seedinfo still reports the seed it was asked to report")

# `seedinfo` and `seed=` share a card: the flag has to be set before the seed is
# applied, and that ordering only holds within one option line.
SEED = ("* optknown seed\nV1 a 0 dc 1\nR1 a 0 1k\n.option seedinfo seed=12345\n"
        ".control\noption noacct\nop\nprint v(a)\n.endc\n.end\n")
rc, out = run(SEED, "sd")
check("a deck asking for seed information gets it", "Seed value" in out,
      [l.strip() for l in out.splitlines() if "Seed" in l][:1])
check("  ... and seedinfo is not reported unknown", not warned(out, "seedinfo"))

print(f"\n  {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
