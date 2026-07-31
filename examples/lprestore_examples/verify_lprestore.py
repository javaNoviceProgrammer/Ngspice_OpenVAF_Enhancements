#!/usr/bin/env python3
"""Enhancement-382: `loadpull` left the user's tuner at its last swept point.

`loadpull` sweeps the R, L and C of the user's own matching network across the
Smith chart. When it finished it left them wherever the last grid point happened
to put them. The old code said as much:

    /* restore something sane on the load (last set values are fine) */

-- a comment with no code under it. The last set values are not a result, merely
where the loop stopped, and the user's network was silently replaced:

    RL  50     -> 84.83 ohm
    LL  1e-15  -> 1.34e-8 H

Any following analysis then ran against the wrong load. On the deck below an
`.ac` moved from 0.4789 to 0.6765 -- a 41% error, with no warning.

THE SAME DEFECT CLASS AS ENHANCEMENT-381, which was `stb` handing its probe
sources back zeroed rather than restored. Both commands borrow parts of the
user's circuit, drive them, and then guess at what "putting them back" means.
`sweep` already had it right (Enhancement-350 captures each swept parameter's
nominal value and restores it at cleanup); this follows that precedent.

A TRAP WORTH RECORDING, because it cost two failed attempts -- and it is TWO
mechanisms, neither of which is what it first looks like.

WHY THE NAME WAS WRONG. ngspice lowercases command text before evaluating it, so
`print @RL[resistance]` works fine. But this code builds the query in C from the
command-line word list, where the name is still `RL`, and that string never passes
through the frontend folding. The fix lower-cases it -- matching what the frontend
would have produced, NOT working around a case-sensitive lookup.

WHY IT WAS SILENT. A missing device does normally report itself
(`print @nosuchdev[resistance]` -> "Error: no such device or model name"). That
comes from `if_getparam`, which is never reached: `lp_eval` calls
`ft_getpnames_from_string(expr, TRUE)`, whose `TRUE` is a VALIDATE flag that
returns NULL on failure with no diagnostic. So the lookup never happens at all.

The first attempt blamed placement instead (reading before loadpull's priming
transient); that was a red herring, and only instrumenting the actual code path
settled which of the two was at fault.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0

NET = """lprestore
Vs src 0 dc 0 ac 1 sin(0 1 1e9)
Rs src n1 50
Ls n1 out 4.7746n
RL out l1 50
LL l1 l2 1e-15
CL l2 0 1e-3
"""

LP = "loadpull -load RL LL CL -out out -drive Vs -f 1e9 -n 9 -gmax 0.6"
NOMINAL = {"rl": 50.0, "ll": 1e-15, "cl": 1e-3}


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(body, tag):
    p = os.path.join(HERE, "_lp_%s.cir" % tag)
    open(p, "w").write(NET + ".control\noption noacct\nset numdgt=12\n"
                       + body + "\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=1800, errors="replace")
    return r.stdout + r.stderr


def params(out):
    return {k: float(v) for k, v in
            re.findall(r"@(\w+)\[\w+\]\s*=\s*([-+0-9.eE]+)", out)}


def main():
    probe = "print @rl[resistance] @ll[inductance] @cl[capacitance]"

    # ---- the defect ---------------------------------------------------------
    after = params(run("%s\n%s" % (LP, probe), "after"))
    for k, want in NOMINAL.items():
        got = after.get(k)
        check("loadpull leaves %s at its original value" % k.upper(),
              got is not None and abs(got - want) <= 1e-12 * max(abs(want), 1e-15),
              "%.6g (nominal %.6g)" % (got, want) if got is not None else "not reported")

    # the consequence: a following .ac must be unaffected
    a = re.search(r"^vm\(out\)\s*=\s*([-+0-9.eE]+)",
                  run("ac lin 1 1e9 1e9\nprint vm(out)", "ref"), re.M)
    b = re.search(r"^vm\(out\)\s*=\s*([-+0-9.eE]+)",
                  run("%s\nac lin 1 1e9 1e9\nprint vm(out)" % LP, "post"), re.M)
    check("an .ac after loadpull matches the same .ac run alone",
          a and b and abs(float(a.group(1)) - float(b.group(1)))
          <= 1e-9 * abs(float(a.group(1))),
          "alone=%s after=%s" % (a.group(1) if a else "?", b.group(1) if b else "?"))

    # ---- ACCEPT HALF: loadpull's own answer must not move -------------------
    out = run(LP, "own")
    m = re.search(r"peak Pout\s*=\s*([-\d.]+)\s*dBm", out)
    check("loadpull still reports a peak Pout", m is not None,
          "peak Pout = %s dBm" % m.group(1) if m else "not reported")

    # running it twice must give the same optimum -- before the fix the second
    # run started from a tuner the first had already moved
    out2 = run("%s\n%s" % (LP, LP), "twice")
    peaks = re.findall(r"peak Pout\s*=\s*([-\d.]+)\s*dBm", out2)
    check("loadpull run twice reports the same optimum",
          len(peaks) == 2 and abs(float(peaks[0]) - float(peaks[1])) < 1e-6,
          "%s then %s" % tuple(peaks) if len(peaks) == 2 else "%d reported" % len(peaks))

    # source-pull mode takes the same code path and must also restore. It needs
    # its own R/L/C on the source side -- the first version of this check passed
    # `Ls` as BOTH the inductor and the capacitor, so `@ls[capacitance]` resolved
    # to nothing, the save was skipped, and the check failed for its own reasons.
    srcnet = ("lprestore-src\n"
              "Vs src 0 dc 0 ac 1 sin(0 1 1e9)\n"
              "Rs src n1 50\n"
              "Ls n1 out 1e-15\n"
              "Cs out l0 1e-3\n"
              "RL out 0 50\n")
    q = os.path.join(HERE, "_lp_srcmode.cir")
    open(q, "w").write(srcnet + ".control\noption noacct\nset numdgt=12\n"
                       "loadpull -source Rs Ls Cs -out out -drive Vs -f 1e9 -n 5 -gmax 0.5\n"
                       "print @rs[resistance] @ls[inductance] @cs[capacitance]\n"
                       ".endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(q)], cwd=HERE,
                       capture_output=True, text=True, timeout=1800, errors="replace")
    sp = params(r.stdout + r.stderr)
    check("source-pull mode also restores its tuner",
          all(k in sp for k in ("rs", "ls", "cs"))
          and abs(sp["rs"] - 50.0) <= 1e-9
          and abs(sp["ls"] - 1e-15) <= 1e-27
          and abs(sp["cs"] - 1e-3) <= 1e-15,
          "Rs=%.6g Ls=%.6g Cs=%.6g" % (sp.get("rs", -1), sp.get("ls", -1), sp.get("cs", -1)))

    for j in os.listdir(HERE):
        if j.startswith("_lp_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
