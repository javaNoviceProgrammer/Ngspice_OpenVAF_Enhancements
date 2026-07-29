#!/usr/bin/env python3
"""Enhancement-366: two more sites of the E-365 stale-binding class, found by
continuing the same sequence-fuzzing campaign AGAINST THE FIXED BUILD.

[E-365](../../enhancements_doc/Enhancement-365.md) fixed `pz` followed by `hb`.
Re-running the campaign with a widened command pool -- the RF/steady-state
commands, `sweep`/`wcd`, and SOLVER SWITCHING (`option klu` / `option sparse`)
between analyses -- took 500 iterations/1 signature to 700/3. Two of the three
were places E-365 had not reached:

  [1] `pz` then `qpss`.  com_qpss.c carried the identical guard com_hb.c had --
      `if (ckt->CKTmatrix == NULL || SMPmatSize(ckt->CKTmatrix) <= 0)` -- which
      asks "is there a matrix?" when the question is "do the device bindings
      point into it". After a `pz` there IS a good matrix, so CKTsetup was
      skipped and CKTload read freed memory. Same fix as E-365: honour
      CKTbindStale with a BALANCED CKTunsetup()/CKTsetup() pair.

  [2] A NULL check that did not guard.  `CREATE_KLU_BINDING_TABLE` in
      klu-binding.h did

          matched = bsearch(...);
          if (matched == NULL) { printf("... not found ..."); }
          here->binding = matched;
          here->ptr = matched->CSC;      /* <- dereferences the NULL it reported */

      so every lookup miss was undefined behaviour, silent on an ordinary build.
      It is reachable: `option klu` + `pz` + any AC-family analysis (`ac`, `sp`,
      `stb`) misses, because `pz` rebuilds ckt->CKTmatrix and the device's COO
      pointer is no longer in the new matrix's bind table. The companion
      CONVERT_KLU_BINDING_TABLE_TO_COMPLEX/_TO_REAL macros then dereferenced the
      same unresolved binding. Now a miss is reported, `binding` is set to NULL
      so downstream can detect it, and both CONVERT macros skip a NULL binding.

WHY THIS FILE NEEDS NO SANITIZER. It checks the consequences an ordinary build
can see: the analyses must still produce their normal answers, and `qpss` after
`pz` must equal `qpss` alone -- `pz` does not change the circuit.

STILL OPEN, and deliberately not papered over. One case remains: under KLU, the
pole-zero block at the end of VSRCbindCSCComplex reads
`here->VSRCibrIbrBinding->CSC_Complex` through a binding that is NOT null but is
STALE -- `CREATE_KLU_BINDING_TABLE` is skipped for that entry (its `branch > 0`
precondition), so the pre-`pz` value survives. It needs the bindings to be torn
down when `pz` rebuilds the matrix, not another guard; a guard cannot tell a
stale pointer from a live one. `examples/pzklu_examples/fuzz/` has the harness
that finds it.
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


NET = """pz/klu binding test
V1 in 0 dc 0.5 ac 1 portnum 1 z0 50
V2 out 0 dc 0 ac 0 portnum 2 z0 50
Rs in mid 1k
Rl mid out 1k
C1 mid 0 1n
"""
NUM = r"[-+0-9.eE]+"


def run(ctl, tag, timeout=180):
    p = os.path.join(HERE, "_pk_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(NET + ".control\noption noacct\nset numdgt=10\n" + ctl + "\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE, capture_output=True,
                       text=True, timeout=timeout, errors="replace")
    return r.returncode, r.stdout + r.stderr


def nums(out, pat):
    return [float(m.group(1)) for m in re.finditer(pat, out or "", re.M)]


def main():
    # [1] qpss after pz must equal qpss alone (E-365's oracle, at the site it missed)
    _, a = run("qpss v1#branch 1e6 1.3e6 hb 3 3", "a")
    _, b = run("pz in 0 mid 0 vol pz\nqpss v1#branch 1e6 1.3e6 hb 3 3", "b")
    pat = r"^\s+mid\s+\(\s*\d+,\s*\d+\)\s+\S+\s+(\S+)"
    va, vb = nums(a, pat), nums(b, pat)
    if not va or not vb:
        check("qpss after pz equals qpss alone", False,
              "no spectrum (alone=%d after=%d)" % (len(va), len(vb)))
    else:
        scale = max(max(abs(x) for x in va), 1e-300)
        worst = max(abs(x - y) for x, y in zip(va, vb)) / scale if len(va) == len(vb) else 1.0
        check("qpss after pz equals qpss alone", worst < 1e-9,
              "max dev %.2e of full scale" % worst)

    # [2] under KLU, pz then an AC-family analysis must still run and produce
    #     its normal answer. Before the fix this path executed a NULL
    #     dereference inside CREATE_KLU_BINDING_TABLE.
    for name, ctl, p2 in (
        ("ac", "ac dec 3 1e6 1e8\nprint vdb(mid)", r"^\s*\d+\s+\S+\s+(%s)\s*$" % NUM),
        ("sp", "sp lin 3 1e6 1e8\nprint S_1_1", r"^\s*\d+\s+\S+\s+(%s)," % NUM),
    ):
        _, plain = run("option klu\n" + ctl, "c_%s" % name)
        _, after = run("option klu\npz in 0 mid 0 vol pz\n" + ctl, "d_%s" % name)
        vp, vf = nums(plain, p2), nums(after, p2)
        ok = bool(vp) and len(vp) == len(vf) and all(
            abs(x - y) <= max(abs(x), 1e-30) * 1e-9 for x, y in zip(vp, vf))
        check("KLU: %s after pz matches %s alone" % (name, name), ok,
              "%d points" % len(vp) if ok else "alone=%d after=%d" % (len(vp), len(vf)))

    # [3] SPARSE was never affected -- it must stay that way
    _, s1 = run("ac dec 3 1e6 1e8\nprint vdb(mid)", "e")
    _, s2 = run("pz in 0 mid 0 vol pz\nac dec 3 1e6 1e8\nprint vdb(mid)", "f")
    p3 = r"^\s*\d+\s+\S+\s+(%s)\s*$" % NUM
    n1, n2 = nums(s1, p3), nums(s2, p3)
    check("SPARSE: ac after pz unchanged", bool(n1) and n1 == n2,
          "%d points identical" % len(n1) if n1 == n2 else "differ")

    for j in os.listdir(HERE):
        if j.startswith("_pk_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
