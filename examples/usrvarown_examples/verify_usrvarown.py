#!/usr/bin/env python3
"""Enhancement-342: ownership of the synthetic user-variable list.

`cp_usrvars()` synthesizes `$plots`, `$curplot`, `$curplottitle`,
`$curplotname` and `$curplotdate` on demand and returns a list its CALLERS
free. Two ownership mistakes sat in that arrangement.

[A] `cp_enqvar()` does not always allocate. When the current plot's environment
    (or the current circuit's variables) already defines a variable of the
    requested name it clears `*tbfreed` and returns a BORROWED pointer into
    that live list. `cp_usrvars()` ignored the flag: it relinked the borrowed
    node (`tv->va_next = v`, orphaning the live list's tail) and the caller
    then freed a node somebody else still owned. A rawfile `Option:` line
    writes the plot environment, so `Option: plots = 1` in a loaded rawfile was
    enough -- heap-use-after-free, SIGSEGV, for all five names.

[B] `cp_remvar()` freed the variable it looked up even when nothing had
    unlinked it. Only the `US_OK` path unlinks; `plots` comes back
    `US_READONLY` and the `curplot*` names come back `US_DONTRECORD`, so the
    node stayed in `uv1` and was freed a second time by the
    `free_struct_variable(uv1)` that ends the function. `unset plots` aborted
    in malloc on a plain deck with no file involved at all.

Both are fixed by respecting ownership: copy a borrowed variable rather than
splicing it, and free the looked-up variable only when it is genuinely ours.

  [1] a rawfile Option: line naming any synthetic variable -- no signal
  [2] `unset` of any synthetic variable -- no abort
  [3] `plots` is still refused as read-only, rather than silently accepted
  [4] all five still read back correctly, and $plots tracks the real plots
  [5] an ordinary variable still sets and unsets
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

NAMES = ("plots", "curplot", "curplotname", "curplottitle", "curplotdate")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=90, deck=None):
    """Run a .control block; return (rc, output). rc is a string on a signal."""
    p = os.path.join(HERE, "_uv.cir")
    with open(p, "w") as f:
        f.write(deck or ("usrvar\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n"
                         ".control\n%s\n.endc\n.end\n" % control))
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


def make_rawfiles():
    """Write an ASCII rawfile per reserved name, each with an Option: line."""
    base = os.path.join(HERE, "_base.raw")
    rc, _ = run("set filetype=ascii\nop\nwrite %s v(out)" % os.path.basename(base))
    if not os.path.exists(base):
        return None
    with open(base, encoding="latin-1") as f:
        src = f.readlines()
    made = {}
    for name in NAMES:
        out = []
        for line in src:
            out.append(line)
            if line.lower().startswith("plotname:"):
                out.append("Option: %s = 1\n" % name)
        p = os.path.join(HERE, "_opt_%s.raw" % name)
        with open(p, "w", encoding="latin-1") as f:
            f.write("".join(out))
        made[name] = p
    return made


def main():
    # ---- [A] the rawfile vector -------------------------------------------
    made = make_rawfiles()
    if not made:
        check("rawfile Option: naming a synthetic variable does not crash",
              False, "could not write the base rawfile")
    else:
        crashed = []
        for name, p in made.items():
            rc, out = run("load %s\necho TOUCH $curplot\nsetplot\necho SURVIVED"
                          % os.path.basename(p))
            if not isinstance(rc, int):
                crashed.append(f"{name}: {rc}")
            elif "SURVIVED" not in out:
                crashed.append(f"{name}: did not finish")
        check("a rawfile Option: line naming any of the five is survivable",
              not crashed, "; ".join(crashed) if crashed else "5/5 names")

    # ---- [B] the unset vector ---------------------------------------------
    aborted = []
    for name in NAMES:
        rc, out = run("op\nunset %s\necho SURVIVED" % name)
        if not isinstance(rc, int):
            aborted.append(f"{name}: {rc}")
        elif "SURVIVED" not in out:
            aborted.append(f"{name}: did not finish")
    check("`unset` of any of the five no longer aborts in malloc",
          not aborted, "; ".join(aborted) if aborted else "5/5 names")

    # ---- [3] the refusal is still a refusal --------------------------------
    rc, out = run("op\nunset plots\necho SURVIVED")
    check("`unset plots` still reports the variable as read-only",
          "read-only" in out,
          next((l.strip()[:52] for l in out.splitlines() if "read-only" in l),
               "no such message"))

    # ---- [4] the values are still right ------------------------------------
    rc, out = run("op\nop\necho PLOTS $plots\necho CUR $curplot\n"
                  "echo NAME $curplotname\necho TITLE $curplottitle\n"
                  "echo DATE $curplotdate")
    def field(k):
        m = re.search(r"^%s (.*)$" % k, out, re.M)
        return m.group(1).strip() if m else ""
    plots, cur = field("PLOTS").split(), field("CUR")
    # two `op` runs on a fresh circuit give the constants plot plus op1 and op2
    ok = (isinstance(rc, int) and "op1" in plots and "op2" in plots
          and cur == "op2" and field("TITLE") != "" and field("DATE") != "")
    check("all five still read back correctly ($plots tracks the real plots)",
          ok, f"$plots={plots} $curplot={cur!r}")

    # ---- [5] ordinary variables unaffected ---------------------------------
    rc, out = run("set myvar = 42\necho GOT $myvar\nunset myvar\necho GONE $myvar")
    was_set = bool(re.search(r"^GOT 42\s*$", out, re.M))
    was_unset = bool(re.search(r"^GONE\s*$", out, re.M))
    check("an ordinary variable still sets and unsets",
          isinstance(rc, int) and was_set and was_unset,
          f"set={was_set} unset={was_unset}")

    # ---- [6] the committed deck --------------------------------------------
    r = subprocess.run([NGSPICE, "-b", "usrvarown.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=120,
                       errors="replace")
    check("the committed reproducer deck runs without a signal",
          r.returncode >= 0 and "SURVIVED" in (r.stdout + r.stderr),
          f"rc={r.returncode}")

    for junk in os.listdir(HERE):
        if junk.startswith("_"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
