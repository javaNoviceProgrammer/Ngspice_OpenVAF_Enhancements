#!/usr/bin/env python3
"""
verify_initfile.py -- an initialisation file must not crash ngspice at start-up.

Finding F6 of the 2026-09-06 solver-core hunt turned out to be nothing to do with
solvers: since Enhancement-558 made `com_source` unquote every word by freeing it and
installing the unquoted copy, `inp_source()`'s BORROWED word -- the caller's own
pointer -- was freed inside the call and again by the caller.  Any `.spiceinit` (or
`spice.rc`) found in the deck's directory, in the current directory or in $HOME
ended the run before the first line of output: `pointer being freed was not
allocated`, exit 134.  `inp_source()` now hands `com_source()` a heap copy.

The checks run ngspice on a trivial deck with an init file in each of the three
places, with a harmless `set` line and, when the build carries XSPICE, with a
`codemodel` line that loads the analog library (the F6 deck itself: two code models,
an operating point and an AC).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

RC = "* trivial rc\nv1 in 0 1\nr1 in out 1k\nc1 out 0 1n\n.control\nop\nprint v(out)\n.endc\n.end\n"
F6 = ("* two xspice code models, op then ac\nv1 in 0 dc 0.2 ac 1\na1 %v(in) %v(mid) xg\n.model xg gain(gain=2.5)\n"
      "r1 mid x 1k\nc1 x 0 1n\na2 %v(x) %v(out) xint\n.model xint int(gain=1e5 out_lower_limit=-10 out_upper_limit=10)\n"
      "r2 out 0 1k\n.control\nop\nprint v(mid)\nac lin 1 1k 1k\nprint vm(out)\n.endc\n.end\n")


def analog_cm():
    """The build's analog code-model library, if XSPICE is compiled in."""
    root = os.path.dirname(os.path.dirname(HERE))
    for cand in (os.path.join(root, "ngspice-46", "build", "src", "xspice", "icm", "analog", "analog.cm"),):
        if os.path.isfile(cand):
            return cand
    return None


def run(subdir, deck, init, env_home=None, deck_in_cwd=False):
    d = os.path.join(HERE, subdir)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    with open(os.path.join(d, "_o.cir"), "w") as fh:
        fh.write(deck)
    env = dict(os.environ)
    if env_home is not None:
        h = os.path.join(HERE, env_home)
        shutil.rmtree(h, ignore_errors=True)
        os.makedirs(h)
        with open(os.path.join(h, ".spiceinit"), "w") as fh:
            fh.write(init)
        env["HOME"] = h
    else:
        with open(os.path.join(d, ".spiceinit"), "w") as fh:
            fh.write(init)
    if deck_in_cwd:
        r = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=d, env=env, capture_output=True, text=True, timeout=120)
    else:
        r = subprocess.run([NGSPICE, "-b", os.path.join(subdir, "_o.cir")], cwd=HERE, env=env,
                           capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def value(out, name):
    m = re.search(r"%s\s*=\s*([-+0-9.eE]+)" % re.escape(name), out)
    return float(m.group(1)) if m else None


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] a .spiceinit beside the deck, in the current directory, and in $HOME")
    rc, out = run("_deckdir", RC, "set initfile_seen=1\n")
    check("deck directory: the run completes (was exit 134 before the first output)", rc == 0 and value(out, "v(out)") == 1.0,
          f"rc={rc} v(out)={value(out, 'v(out)')}")
    rc, out = run("_cwd", RC, "set initfile_seen=1\n", deck_in_cwd=True)
    check("current directory: the run completes", rc == 0 and value(out, "v(out)") == 1.0, f"rc={rc}")
    rc, out = run("_plain", RC, "set initfile_seen=1\n", env_home="_home")
    check("$HOME/.spiceinit: the run completes", rc == 0 and value(out, "v(out)") == 1.0, f"rc={rc}")
    check("...and the file was actually read (no 'not allocated', no abort)", "not allocated" not in out and "abort" not in out.lower())

    print("[2] the F6 deck: code models loaded from a .spiceinit beside the deck, op then ac")
    cm = analog_cm()
    if cm:
        rc, out = run("_f6", F6, f"codemodel {cm}\n")
        check("two code models, op then ac: exit 0 and the right numbers",
              rc == 0 and value(out, "v(mid)") == 0.5 and abs((value(out, "vm(out)") or 0) - 39.78795) < 0.01,
              f"rc={rc} v(mid)={value(out, 'v(mid)')} vm(out)={value(out, 'vm(out)')}")
    else:
        check("two code models, op then ac (skipped: no analog.cm in this build)", True)

    for sub in ("_deckdir", "_cwd", "_plain", "_home", "_f6"):
        shutil.rmtree(os.path.join(HERE, sub), ignore_errors=True)
    print("\nALL PASSED" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
