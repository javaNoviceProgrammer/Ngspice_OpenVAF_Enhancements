#!/usr/bin/env python3
"""Enhancement-372: `unset plots` reported a bogus "Internal Error".

Found by a PLOT-LIFECYCLE sequence fuzzer -- random analyses interleaved with
plot-management commands (`destroy`, `setplot`, `unset plots`, `write`/`load`,
`fft`, `linearize`, `remcirc`) run under ASan. That area was chosen because it is
where [E-342](../../enhancements_doc/Enhancement-342.md) (a borrowed-pointer
use-after-free via `unset plots`) and
[E-345](../../enhancements_doc/Enhancement-345.md) came from, and because
[E-371](../../enhancements_doc/Enhancement-371.md) had just added a new allocation
and new pointer arithmetic to it. The harness is in `fuzz/`.

It fired in 18 of 120 cases and minimised to ONE command, on the shipped binary:

    unset plots
    -->  Error: plots is read-only.
         cp_remvar: Internal Error: var 112

TWO SEPARATE DEFECTS in cp_remvar() (src/frontend/variable.c):

  [1] THE MESSAGE PRINTED AN ASCII CODE, NOT A NAME. The signature is
      `cp_remvar(char *varname)`, and the format was

          fprintf(cp_err, "cp_remvar: Internal Error: var %d\\n", *varname);

      -- `*varname` dereferences the string to its FIRST CHARACTER. 112 is 'p',
      the first letter of "plots"; `unset curplot` reported "var 99", which is
      'c'. The diagnostic never named the variable it was complaining about.

  [2] IT WAS NOT AN INTERNAL ERROR. The branch is guarded by `if (*p)`, and `*p`
      non-NULL only means the variable WAS FOUND in one of the lists walked just
      above -- the normal state for `plots` and `curplot`. So it fired on 100% of
      ordinary `unset` calls for them. An "internal error" that valid user input
      reaches every single time carries no signal.

THE FIX drops both spurious prints. For US_READONLY the "read-only" message is
already the complete and correct answer, and nothing is unlinked or freed in that
case -- which is exactly right for a read-only variable -- so removing the noise
changes no behaviour. For US_DONTRECORD the case's own comment says "Do
nothing...", and its siblings curplotname / curplottitle / curplotdate were always
silent; `curplot` now matches them.

The `curplotname` rows below are CONTROLS: they were already silent and must stay
that way, which is what shows the change is confined to the two affected cases.
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


def run(ctl, tag, timeout=120):
    p = os.path.join(HERE, "_uv_%s.cir" % tag)
    with open(p, "w") as f:
        f.write("unset var\nV1 in 0 dc 1\nR1 in mid 1k\nR2 mid 0 1k\n"
                ".control\noption noacct\n" + ctl + "\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout, errors="replace")
    return r.returncode, r.stdout + r.stderr


IE = re.compile(r"Internal Error", re.I)


def main():
    # [1] the two variables that used to trip it. `plots` keeps its read-only
    #     diagnostic; `curplot` is silent like its US_DONTRECORD siblings.
    rc, out = run("unset plots", "a")
    check("unset plots: no bogus Internal Error", not IE.search(out),
          "clean" if not IE.search(out) else IE.search(out).group(0))
    check("unset plots: keeps the read-only diagnostic", "read-only" in out,
          "reported" if "read-only" in out else "MESSAGE LOST")

    rc, out = run("unset curplot", "b")
    check("unset curplot: no bogus Internal Error", not IE.search(out),
          "clean" if not IE.search(out) else IE.search(out).group(0))

    # [2] controls -- already silent, must not change
    for v in ("curplotname", "curplottitle", "curplotdate"):
        rc, out = run("unset %s" % v, "c_" + v)
        check("unset %s unchanged (control)" % v, not IE.search(out), "silent")

    # [3] no ASCII code can leak into a message again: after an analysis exists,
    #     unsetting a read-only var must still name it in words, never as a number
    rc, out = run("op\nunset plots", "d")
    m = re.search(r"var \d+", out)
    check("no numeric 'var <N>' in any message", m is None,
          "none" if m is None else "still prints %r" % m.group(0))

    # [4] the surrounding machinery still works: a NORMAL variable must still be
    #     settable and unsettable, or the fix would have broken `unset` itself
    # `op` is here so batch mode has an analysis to run -- without one ngspice
    # exits non-zero on "no simulations run", which says nothing about `unset`.
    rc, out = run("op\nset myvar=42\necho GOT $myvar\nunset myvar\n"
                  "echo AFTER $myvar", "e")
    got = re.search(r"^GOT 42", out, re.M)
    gone = re.search(r"^AFTER\s*$", out, re.M)
    check("an ordinary variable still sets and unsets", rc == 0 and bool(got) and bool(gone),
          "set 42, unset -> empty" if (got and gone)
          else "rc=%d set=%s unset=%s" % (rc, bool(got), bool(gone)))

    # [5] the sequence the fuzzer actually found it with must run clean
    rc, out = run("noise v(mid) V1 dec 3 1e3 1e5\nunset plots\ntf v(mid) V1\n"
                  "remcirc\ndestroy ac1\nsetplot op1\nsweep V1 0 1 0.34", "f")
    check("the fuzzer's minimised sequence is clean", not IE.search(out),
          "clean" if not IE.search(out) else IE.search(out).group(0))

    for j in os.listdir(HERE):
        if j.startswith("_uv_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
