#!/usr/bin/env python3
"""Enhancement-594: `.option saveused` no longer aborts a noise or sp analysis.

The option (E-469) infers a save list from the control block and the deck's
output cards. A noise run's plot holds onoise_spectrum, inoise_spectrum and the
totals, an sp run's holds S_i_j, Y_i_j, Z_i_j and Rbase -- no node at all -- so
the inferred list (`out` from the `noise v(out) v1 ...` line itself, `in` from
a `print v(in)`) matched nothing of theirs and the analysis was refused:
"no data saved for Noise analysis; analysis not run", on every deck with a
noise run (F1 of the 2026-09-09 dig). Two more slips sat behind the sp half:
a `save` name is lowercased by the deck reader while the analysis publishes
`S_2_1` in mixed case and the matcher compared with strcmp, so a hand-written
`save S_2_1` never matched in stock either; and the E-417 dedup in
ft_getSaves() dropped a second `save all` that differed only in its analysis
restriction.

Checks:
  [1] noise under the option: runs, onoise_total equals the unrestricted run
  [2] the per-generator form (pts_per_summary): the noise1 vector set is
      identical to the unrestricted run's
  [3] a `.noise` card run through `run` works too
  [4] an ac beside the noise run is still pruned to what the block names
  [5] sp under the option: S_2_1 prints and `wrs2p` writes a full file
  [6] stock, no option: `save S_2_1 in` before sp now matches (case)
  [7] stock semantics untouched: `save in` alone before sp still drops S_2_1,
      and `save out` before noise still aborts the noise run
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="savenoise_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


NOISE_CKT = "v1 s 0 dc 1 ac 1\nrs s in 1\nr1 in out 1k\nc1 out 0 100n\n"
SP_CKT = ("V1 in 0 dc 0 ac 1 portnum 1 z0 50\nr1 in out 1k\nc1 out 0 100n\n"
          "V2 out 0 dc 0 ac 0 portnum 2 z0 50\n")


def run(ckt, ctl, tag, opt=True, cards=""):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* savenoise {tag}\n{ckt}{'.option saveused' if opt else ''}\n{cards}"
                f".control\nset numdgt=8\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=120, cwd=WORK)
    return p.stdout + p.stderr


def value(out, name):
    m = re.search(r"(?mi)^" + re.escape(name) + r" = (\S+)", out)
    return m.group(1) if m else None


def printed(out, name):
    """True when `print name` produced either the scalar `name = v` form or,
    for a vector of more than one point, the table whose header names it"""
    return (value(out, name) is not None
            or re.search(r"(?mi)^Index\s+\S+\s+" + re.escape(name) + r"\b", out) is not None)


def vectors(out):
    """the vector names of the LAST `display` in the output"""
    blocks = out.split("Here are the vectors currently active:")
    if len(blocks) < 2:
        return set()
    return set(re.findall(r"(?m)^\s+(\S+)\s+:\s", blocks[-1]))


ABORT = "no data saved for Noise analysis"
print("Enhancement-594: saveused and an analysis whose plot holds no node\n")

# ------------------------------------------------------------- [1] ---
CTL1 = "noise v(out) v1 dec 2 100 10k\nprint noise2.onoise_total"
ref = run(NOISE_CKT, CTL1, "t1_ref", opt=False)
out = run(NOISE_CKT, CTL1, "t1")
check("[1] noise under the option is not refused", ABORT not in out, out[-200:])
check("[1] ...and onoise_total equals the unrestricted run's",
      value(out, "noise2.onoise_total") is not None
      and value(out, "noise2.onoise_total") == value(ref, "noise2.onoise_total"),
      f"{value(out, 'noise2.onoise_total')} vs {value(ref, 'noise2.onoise_total')}")

# ------------------------------------------------------------- [2] ---
CTL2 = "noise v(out) v1 dec 2 100 10k 1\nsetplot noise1\ndisplay"
ref = run(NOISE_CKT, CTL2, "t2_ref", opt=False)
out = run(NOISE_CKT, CTL2, "t2")
check("[2] the per-generator form keeps the same noise1 vector set",
      vectors(out) == vectors(ref) and "onoise_r1_thermal" in vectors(out),
      f"{sorted(vectors(out))} vs {sorted(vectors(ref))}")

# ------------------------------------------------------------- [3] ---
out = run(NOISE_CKT, "run\nprint noise2.onoise_total", "t3",
          cards=".noise v(out) v1 dec 2 100 10k\n")
check("[3] a `.noise` card run through `run` works too",
      ABORT not in out and value(out, "noise2.onoise_total") is not None, out[-200:])

# ------------------------------------------------------------- [4] ---
out = run(NOISE_CKT, "ac lin 1 1k 1k\nprint v(out)\nnoise v(out) v1 dec 2 100 10k\n"
          "print noise2.onoise_total\nsetplot ac1\ndisplay", "t4")
v = vectors(out)
check("[4] the ac beside the noise run is still pruned to `out`",
      "out" in v and "in" not in v and "s" not in v and value(out, "noise2.onoise_total") is not None,
      f"{sorted(v)}")

# ------------------------------------------------------------- [5] ---
out = run(SP_CKT, "sp lin 3 1k 10k\nprint v(in)\nprint S_2_1\nwrs2p t5.s2p\ndisplay", "t5")
v = vectors(out)
s2p = os.path.join(WORK, "t5.s2p")
rows = [l for l in open(s2p).read().splitlines() if l.strip() and l[0] not in "!#"] if os.path.exists(s2p) else []
check("[5] sp under the option: S_2_1 prints",
      printed(out, "s_2_1") and "not available" not in out, out[-200:])
check("[5] ...the plot holds every S/Y/Z entry and Rbase",
      {"S_1_1", "S_2_2", "Y_1_2", "Z_2_1", "Rbase", "in"} <= v, f"{sorted(v)}")
check("[5] ...and `wrs2p` writes three data rows", len(rows) == 3, f"{len(rows)} rows")

# ------------------------------------------------------------- [6] ---
out = run(SP_CKT, "save S_2_1 in\nsp lin 3 1k 10k\nprint S_2_1\ndisplay", "t6", opt=False)
check("[6] stock: `save S_2_1 in` before sp now matches the mixed-case vector",
      printed(out, "s_2_1") and "nothing of that name" not in out
      and vectors(out) == {"S_2_1", "in", "frequency"}, f"{sorted(vectors(out))}")

# ------------------------------------------------------------- [7] ---
out = run(SP_CKT, "save in\nsp lin 3 1k 10k\nprint S_2_1", "t7a", opt=False)
check("[7] stock: `save in` alone still drops S_2_1 -- an explicit list is obeyed",
      not printed(out, "s_2_1") and "not available" in out, out[-160:])
out = run(NOISE_CKT, "save out\nnoise v(out) v1 dec 2 100 10k\nprint noise2.onoise_total", "t7b", opt=False)
check("[7] stock: `save out` before noise still refuses the run, as it always did",
      ABORT in out, out[-160:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
