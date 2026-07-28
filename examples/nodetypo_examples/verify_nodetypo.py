#!/usr/bin/env python3
"""Enhancement-349: an analysis card that names a node which does not exist.

`INPtermInsert()` is create-or-find. Right for a device card -- `R1 in out 1k`
is what brings `out` into existence -- and wrong for `.tf v(out) v1`, which only
REFERS to it. A mistyped name was quietly created as a new unconnected node,
which then read back as a perfectly plausible 0 V.

From the .control section it was worse: `CKTsetup()` has already snapshotted the
node list and sized the matrix, so the extra node makes the tail check at the end
of `CKTunsetup()` fail -- and that calls `controlled_exit(EXIT_FAILURE)`. Seven
commands killed the process on one transposed letter.

Analysis cards now resolve through `INPtermSearch()` (lookup-only) and report an
unknown name, while still creating when the circuit is NOT yet set up -- because
a .tf card may legally sit ahead of the devices that define its nodes.

  [1] all seven commands survive an unknown node name after an op
  [2] the same reference as a DECK card still parses (no regression)
  [3] a .tf card placed BEFORE its devices still resolves, and to the same
      numbers -- the deck-order tolerance the fix had to preserve
  [4] valid invocations still return their original answers
  [5] the error names the offending node instead of inventing it
  [6] the committed reproducer deck survives
"""
import os
import re
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

DECK = ("nodetypo\n"
        "V1 in 0 dc 1 ac 1 sin(0 1 1e6)\n"
        "R1 in out 1k\n"
        "R2 out 0 3k\n"
        "C1 out 0 1p\n")

# every analysis command that resolves a node name, given one that does not exist
BOGUS = {
    "tf":     "tf v(zznode) v1",
    "pz":     "pz zznode 0 out 0 vol pol",
    "noise":  "noise v(zznode) v1 dec 2 100 1e4",
    "sens":   "sens v(zznode)",
    "pss":    "pss 1meg 1u zznode 1024 10 50 5u",
    "pxf":    "pxf dec 2 1e3 1e5 1",
    "psp":    "psp dec 2 1e3 1e5 1",
}
# pxf/psp run off a preceding PSS, whose oscnode is where the typo lands
PRELUDE = {"pxf": "pss 1meg 1u zznode 1024 10 50 5u",
           "psp": "pss 1meg 1u zznode 1024 10 50 5u"}

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=180, deck=None, whole=None):
    p = os.path.join(HERE, "_nt.cir")
    with open(p, "w") as f:
        f.write(whole or ("%s.control\noption noacct\nset numdgt=10\n%s\n"
                          "echo SURVIVED\n.endc\n.end\n" % (deck or DECK, control)))
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG", ""
    finally:
        if os.path.exists(p):
            os.remove(p)
    if r.returncode < 0:
        try:
            nm = signal.Signals(-r.returncode).name
        except ValueError:
            nm = str(-r.returncode)
        return "SIG" + nm, r.stdout + r.stderr
    return r.returncode, r.stdout + r.stderr


def nums(text):
    return re.findall(r"[-+]?\d+\.\d+e[-+]\d+", text)


def main():
    # ---- [1] the fatal vector ----------------------------------------------
    died = []
    for name, cmd in BOGUS.items():
        body = "op\n" + (PRELUDE[name] + "\n" if name in PRELUDE else "") + cmd
        rc, out = run(body)
        if "incomplete CKTunsetup" in out or not isinstance(rc, int):
            died.append(f"{name}: {rc}")
    check("no command kills the process on an unknown node name",
          not died, "; ".join(died) if died else f"{len(BOGUS)}/{len(BOGUS)} survive")

    # ---- [2] the same reference in the DECK still parses --------------------
    rc, out = run(None, whole=DECK + ".tf v(zznode) v1\n.end\n")
    check("the same reference as a deck card still parses",
          isinstance(rc, int) and "incomplete CKTunsetup" not in out, f"rc={rc}")

    # ---- [3] deck-order tolerance the fix had to preserve -------------------
    fwd = ("fwd\n.tf v(out) v1\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 3k\n.end\n")
    rc, out = run(None, whole=fwd)
    got = dict(re.findall(r"(transfer_function|output_impedance_at_v\(out\)|"
                          r"v1#input_impedance)\s*=\s*(\S+)", out))
    ok = (isinstance(rc, int)
          and abs(float(got.get("transfer_function", "nan")) - 0.75) < 1e-9
          and abs(float(got.get("output_impedance_at_v(out)", "nan")) - 750.0) < 1e-6
          and abs(float(got.get("v1#input_impedance", "nan")) - 4000.0) < 1e-6)
    check("a .tf card placed BEFORE its devices still resolves correctly",
          ok, ", ".join(f"{k}={v}" for k, v in sorted(got.items())) or f"rc={rc}")

    # ---- [4] valid invocations are untouched --------------------------------
    moved = []
    for label, body, want in (
            ("tf",    "op\ntf v(out) v1\nprint transfer_function", "7.5"),
            ("pz",    "op\npz in 0 out 0 vol pol\nprint pole(1)", None),
            ("noise", "noise v(out) v1 dec 3 100 1e6\nsetplot noise1\n"
                      "print onoise_spectrum[0]", None),
            ("sens",  "sens v(out)\nprint all", None)):
        rc, out = run(body)
        if not (isinstance(rc, int) and rc == 0 and "SURVIVED" in out and nums(out)):
            moved.append(f"{label}: rc={rc}")
        elif want and not out.count("7.500000"):
            moved.append(f"{label}: value moved")
    check("valid invocations still run and still return numbers",
          not moved, "; ".join(moved) if moved else "4/4 unchanged")

    # ---- [5] the message names the node -------------------------------------
    rc, out = run("op\ntf v(zznode) v1")
    check("the unknown name is reported rather than invented",
          "zznode" in out and "no such node" in out.lower(),
          "reported" if "no such node" in out.lower() else "not reported")

    # ---- [6] the committed deck ---------------------------------------------
    r = subprocess.run([NGSPICE, "-b", "nodetypo.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=240,
                       errors="replace")
    check("the committed reproducer deck runs without a signal",
          r.returncode >= 0 and "SURVIVED" in (r.stdout + r.stderr)
          and "incomplete CKTunsetup" not in (r.stdout + r.stderr),
          f"rc={r.returncode}")

    for junk in os.listdir(HERE):
        if junk.startswith("_"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
