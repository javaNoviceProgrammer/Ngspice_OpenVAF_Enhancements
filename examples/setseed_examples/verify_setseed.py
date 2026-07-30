#!/usr/bin/env python3
"""Enhancement-374: `setseed` did not seed TRANSIENT NOISE.

Found by a correctness campaign over ngspice's commands. Two identical decks with
`setseed 42` produced DIFFERENT noise waveforms, while `setseed 42` followed by
`rnd(100)` returned exactly 50.0 both times -- so the command itself worked, just
not for the generator transient noise draws from.

WHY. `#define WaGauss` (ngspice.h) selects the Wallace normal generator, and
`initw()` in wallace.c opened with

    srand((unsigned int) getpid());
    // srand(17);
    TausSeed();

`initw()` runs at STARTUP and fills its two pools from that getpid()-derived
stream. `GaussWa` then draws from the pools. A later `setseed` reset srand and the
Tausworthe state, but nothing refilled pools that already existed, so the samples
kept coming from the process-id stream.

THE FIX has three parts, because moving the seeding alone is not enough:
  * `initw()` no longer calls srand() -- it seeds from whatever state the caller
    established, so it cannot clobber a user seed.
  * the two startup call sites (main.c, sharedspice.c) now do the
    `srand(getpid())` themselves, so an unseeded run is still random per run.
  * `com_sseed()` calls `destroy_wallace(); initw();` so a new seed actually
    rebuilds the pools.

A TRAP WORTH RECORDING. The first version of the com_sseed change was guarded with
`#if defined(WaGauss) && defined(SIMULATOR)`, and SIMULATOR is NOT defined for
library sources like randnumb.c -- exactly the situation
[E-367](../../enhancements_doc/Enhancement-367.md) documented. The whole fix
compiled out silently and setseed still did not reproduce. The guard is now on
WaGauss alone.

The THREE properties below are what correctness means here, and the third matters
as much as the first: seeding must not make an unseeded run deterministic.
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


def wave(seedcmd, tag):
    """Run a noisy transient and return the waveform text."""
    out = os.path.join(HERE, "_ss_%s.txt" % tag)
    if os.path.exists(out):
        os.remove(out)
    p = os.path.join(HERE, "_ss_%s.cir" % tag)
    with open(p, "w") as f:
        f.write("setseed\nVn nz 0 dc 0 trnoise(1m 1e-8 0 0)\nRz nz 0 1k\n"
                ".control\noption noacct\n%s\ntran 1e-8 300n 0 1e-8\n"
                "wrdata _ss_%s.txt v(nz)\n.endc\n.end\n" % (seedcmd, tag))
    subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                   capture_output=True, text=True, timeout=300, errors="replace")
    return open(out, errors="replace").read() if os.path.exists(out) else None


def scalar(seedcmd, tag):
    p = os.path.join(HERE, "_ss_%s.cir" % tag)
    with open(p, "w") as f:
        f.write("rnd\nV1 in 0 dc 1\nR1 in 0 1k\n.control\noption noacct\n"
                "set numdgt=17\n%s\nlet a = rnd(100)\nprint a\n.endc\n.end\n" % seedcmd)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    m = re.search(r"^a\s*=\s*([-+0-9.eE]+)", r.stdout + r.stderr, re.M)
    return float(m.group(1)) if m else None


def main():
    # [1] the same seed must reproduce the noise stream exactly
    a, b = wave("setseed 42", "a"), wave("setseed 42", "b")
    check("same seed reproduces the transient-noise waveform",
          a is not None and a == b,
          "byte-identical" if (a and a == b) else "waveforms differ")

    # [2] a different seed must give a different stream (else it is not seeding,
    #     it is just pinning one constant sequence)
    c = wave("setseed 99", "c")
    check("a different seed gives a different waveform",
          a is not None and c is not None and a != c,
          "42 != 99" if (a and c and a != c) else "seeds are not distinguishable")

    # [3] and WITHOUT setseed a run must still be random per process -- this is
    #     the property that a naive "just srand(17)" fix would have destroyed
    d, e = wave("", "d"), wave("", "e")
    check("no setseed still varies run to run (default stays random)",
          d is not None and e is not None and d != e,
          "two unseeded runs differ" if (d and e and d != e)
          else "unseeded runs became deterministic")

    # [4] control: the non-noise RNG was always seeded correctly and must stay so
    r1, r2 = scalar("setseed 42", "r1"), scalar("setseed 42", "r2")
    check("control: setseed still fixes rnd() (was already working)",
          r1 is not None and r1 == r2, "rnd(100) = %s twice" % r1)

    # [5] and the transient noise itself must still be NOISE, not a constant --
    #     a fix that froze the generator would satisfy [1] and be useless
    if a:
        vals = [float(x.split()[1]) for x in a.strip().splitlines()
                if len(x.split()) >= 2]
        spread = (max(vals) - min(vals)) if vals else 0.0
        check("the seeded stream is still non-trivial noise",
              spread > 1e-9, "peak-to-peak %.3e over %d points" % (spread, len(vals)))
    else:
        check("the seeded stream is still non-trivial noise", False, "no waveform")

    for j in os.listdir(HERE):
        if j.startswith("_ss_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
