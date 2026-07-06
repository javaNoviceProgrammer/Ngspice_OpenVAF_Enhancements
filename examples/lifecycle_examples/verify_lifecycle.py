#!/usr/bin/env python3
"""
verify_lifecycle.py -- Enhancement-81: session-lifecycle + memory audit,
end-to-end through the committed openvaf-r + ngspice. Interactive
workflows with OSDI devices -- re-sourcing, circuit removal, long
reset/alter loops, plot management -- probed for correctness and bounded
memory, plus the two resource fixes this enhancement ships.

  [1] re-sourcing the same deck gives the identical result; remcirc +
      sourcing a different deck resolves the new circuit;
  [2] a 100-iteration `reset` loop (the E-66 Monte-Carlo idiom) keeps the
      solution exact and grows the ngspice program size by a bounded
      amount (well under 20 kB per reset);
  [3] plots accumulate one per analysis (the documented E-66 trap) and
      `destroy all` genuinely frees them -- the plot numbering restarts;
  [4] the pre_osdi already-loaded note now carries the restart hint, and
      the stale-model behavior it warns about is pinned: overwriting a
      loaded .osdi and re-loading the same path keeps the OLD model
      (matching pre-E-76 shadowing; restart ngspice to reload);
  [5] `set no_mem_check` is accepted and simulation proceeds normally --
      it now also silences the ft_ckspace "approaching max data size"
      warning (the warning itself needs ~95% RAM pressure, untestable in
      a bounded suite; the opt-out path is exercised, the latch is code-
      reviewed).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE

checks = []


def check(label, cond):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")


def compile_va(src, out):
    subprocess.run([OPENVAF, src, "-o", out], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(deck, name):
    open(os.path.join(HERE, f"_{name}.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", f"_{name}.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def currents(out):
    return [float(m) for m in re.findall(r"-i\(vin\)\s*=\s*([-\d.e+]+)", out)]


def main():
    compile_va("lres.va", "lres.osdi")
    for name, r in (("_deck1.cir", "1k"), ("_deck2.cir", "2k")):
        open(os.path.join(HERE, name), "w").write(
            f"* deck {r}\nvin in 0 dc 1\nn1 in 0 mm\n.model mm lres(r={r})\n.end\n")
    open(os.path.join(HERE, "_deck0.cir"), "w").write(
        "* default-r deck\nvin in 0 dc 1\nn1 in 0 mm\n.model mm lres\n.end\n")

    print("[1] re-source identity + remcirc/new-deck resolution")
    out = run("* lifecycle\n.control\npre_osdi lres.osdi\n"
              "source _deck1.cir\nop\nprint -i(vin)\n"
              "source _deck1.cir\nop\nprint -i(vin)\n"
              "remcirc\nsource _deck2.cir\nop\nprint -i(vin)\n"
              ".endc\n.end\n", "lc")
    i = currents(out)
    check("same deck re-sourced twice: identical 1 mA",
          len(i) >= 2 and abs(i[0] - 1e-3) < 1e-12 and i[0] == i[1])
    check("remcirc + deck2 resolves the new circuit (0.5 mA)",
          len(i) >= 3 and abs(i[2] - 0.5e-3) < 1e-12)

    print("[2] 100-iteration reset loop: exact + bounded memory growth")
    out = run("* resets\nvin in 0 dc 1\nn1 in 0 mm\n.model mm lres(r=1k)\n"
              ".control\npre_osdi lres.osdi\nrusage space\n"
              "let k = 0\nwhile k < 100\n  reset\n  op\n  let k = k + 1\nend\n"
              "print -i(vin)\nrusage space\n.endc\n.end\n", "rst")
    sizes = [float(m) for m in
             re.findall(r"Current ngspice program size\s*=\s*([\d.]+)\s*MB", out)]
    i = currents(out)
    check("solution exact after 100 resets",
          i and abs(i[0] - 1e-3) < 1e-12)
    growth_kb = (sizes[1] - sizes[0]) * 1024 / 100 if len(sizes) == 2 else None
    check(f"program-size growth bounded "
          f"({growth_kb:.1f} kB/reset < 20)" if growth_kb is not None
          else "program-size growth MISSING DATA",
          growth_kb is not None and growth_kb < 20.0)

    print("[3] plot accumulation + destroy all")
    out = run("* plots\nvin in 0 dc 1\nn1 in 0 mm\n.model mm lres(r=1k)\n"
              ".control\npre_osdi lres.osdi\n"
              "let j = 0\nwhile j < 10\n  tran 1u 10u\n  let j = j + 1\nend\n"
              "echo CUR $curplot\ndestroy all\ntran 1u 10u\n"
              "echo CUR $curplot\n.endc\n.end\n", "plots")
    curs = re.findall(r"CUR\s+(\S+)", out)
    check(f"plots accumulate per analysis (10 trans -> {curs[0] if curs else '?'})",
          len(curs) == 2 and curs[0] == "tran10")
    check("destroy all frees them (numbering restarts at tran1)",
          len(curs) == 2 and curs[1] == "tran1")

    print("[4] pre_osdi reload semantics (the E-76 note, now with the hint)")
    compile_va("lres.va", "_lr.osdi")
    open(os.path.join(HERE, "_lrv2.va"), "w").write(
        open(os.path.join(HERE, "lres.va")).read().replace("r = 1k", "r = 4k"))
    compile_va("_lrv2.va", "_lrv2.osdi")
    out = run("* reload\n.control\npre_osdi _lr.osdi\n"
              "source _deck0.cir\nop\nprint -i(vin)\n"
              "shell cp _lrv2.osdi _lr.osdi\n"
              "pre_osdi _lr.osdi\nremcirc\nsource _deck0.cir\nop\n"
              "print -i(vin)\n.endc\n.end\n", "reload")
    check("note carries the restart hint",
          "restart ngspice to load a recompiled file" in out)
    i = currents(out)
    check("stale-model behavior pinned (old default persists in-session)",
          len(i) >= 2 and abs(i[0] - 1e-3) < 1e-12 and i[0] == i[1])

    print("[5] no_mem_check accepted (now also covers ft_ckspace)")
    out = run("* nmc\nvin in 0 dc 1\nn1 in 0 mm\n.model mm lres(r=1k)\n"
              ".control\nset no_mem_check\npre_osdi lres.osdi\nop\n"
              "print -i(vin)\n.endc\n.end\n", "nmc")
    i = currents(out)
    check("simulation normal under no_mem_check",
          i and abs(i[0] - 1e-3) < 1e-12)

    n_pass = sum(checks)
    n_fail = len(checks) - n_pass
    print()
    print(("ALL PASS" if n_fail == 0 else "FAILURES")
          + f": {n_pass} passed, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
