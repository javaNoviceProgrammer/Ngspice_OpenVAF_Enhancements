#!/usr/bin/env python3
"""Enhancement-231: CSV output for `wrdata` (`set wr_csv` + `wrdata -csv`).

ngspice's `wrdata` writes whitespace-separated columns (each vector prefixed by
its own scale column); the only knobs were `wr_singlescale`, `wr_vecnames`,
`wr_onespace`, and `numdgt`. There was no way to emit a real comma-separated
file -- the only `-csv` in the tree was `show -csv` (device-parameter tables).

This adds a first-class CSV mode to `wrdata`:
  * `set wr_csv`  -- boolean option read in ft_writesimple(); when set, columns
                    are comma-separated, a single shared scale column is written
                    (implies wr_singlescale), and a header row of vector names is
                    emitted (implies wr_vecnames).
  * `wrdata -csv <file> <vec...>` -- a per-call alias for `set wr_csv`, accepted
                    in any argument position; it enables CSV for that one write
                    and restores the prior global state afterwards (no leak).
Complex vectors (.ac) become two columns (real, imag). Default `wrdata` output
is byte-for-byte unchanged.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import csv
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(deck):
    open(os.path.join(HERE, "_c.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "_c.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def _is_float(x):
    try:
        float(x)
        return True
    except ValueError:
        return False


def readfile(name):
    p = os.path.join(HERE, name)
    return open(p).read() if os.path.exists(p) else None


def rows(name):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        return None
    return list(csv.reader(open(p)))


# ------------------------------------------------------------ DC divider: op
# V1=1, R1=2k (in->out), R2=1k (out->0)  =>  v(out)=1/3, v(in)=1
run("""* csv dc divider
V1 in 0 dc 1
R1 in out 2k
R2 out 0 1k
.control
op
wrdata def.dat v(out) v(in)
set wr_csv
wrdata setvar.csv v(out) v(in)
unset wr_csv
wrdata -csv flag_first.csv v(out) v(in)
wrdata flag_mid.csv v(out) -csv v(in)
wrdata flag_last.csv v(out) v(in) -csv
wrdata after.dat v(out) v(in)
.endc
.end
""")

# 1. default output unchanged: whitespace-separated, no commas
d = readfile("def.dat")
check("default wrdata is unchanged (space-separated, no commas)",
      d is not None and "," not in d, repr(d.splitlines()[0]) if d else "no file")

# 2. `set wr_csv` produces a header + comma-separated data
sv = rows("setvar.csv")
ok = (sv is not None and sv[0] == ["in", "v(out)", "v(in)"] and len(sv) == 2)
val_ok = ok and abs(float(sv[1][1]) - 1.0 / 3.0) < 1e-6 and abs(float(sv[1][2]) - 1.0) < 1e-9
check("`set wr_csv` writes a header row and comma-separated values", val_ok,
      f"header={sv[0]} data={sv[1]}" if sv else "no file")

# 3. `wrdata -csv` in every position matches `set wr_csv`
for pos, fn in (("first", "flag_first.csv"), ("mid", "flag_mid.csv"),
                ("last", "flag_last.csv")):
    r = rows(fn)
    ok = r is not None and r == sv
    check(f"`wrdata -csv` ({pos} position) is identical to `set wr_csv`", ok,
          f"{r}" if not ok else "")

# 4. the -csv flag does not leak into the following default write
af = readfile("after.dat")
check("`-csv` does not leak: the next plain wrdata is space-separated again",
      af is not None and "," not in af,
      repr(af.splitlines()[0]) if af else "no file")

# 5. same numbers in default and CSV (just a different separator)
if d and sv:
    dcols = d.splitlines()[0].split()          # scale v(out) scale v(in)
    same = (abs(float(dcols[1]) - float(sv[1][1])) < 1e-12 and
            abs(float(dcols[3]) - float(sv[1][2])) < 1e-12)
    check("CSV values equal the default-format values bit-for-bit", same,
          f"default={dcols} csv={sv[1]}")

# ------------------------------------------------------------ AC: complex cols
run("""* csv ac complex
V1 in 0 dc 0 ac 1
R1 in out 1k
C1 out 0 159n
.control
ac dec 2 100 1k
wrdata ac.csv -csv v(out)
.endc
.end
""")
ac = rows("ac.csv")
ok = (ac is not None and ac[0] == ["frequency", "v(out)", "v(out)"] and
      len(ac) >= 4)
parse_ok = ok and all(len(r) == 3 for r in ac) and \
    all(_is_float(x) for x in ac[1])
check("`.ac` (complex) writes real,imag as two columns under a frequency scale",
      parse_ok, f"header={ac[0]} n={len(ac)}" if ac else "no file")

# ------------------------------------------------------------ tran: time scale
run("""* csv tran
V1 in 0 dc 0 pulse(0 1 0 1u 1u 5u 10u)
R1 in out 1k
C1 out 0 1n
.control
tran 1u 10u
wrdata tr.csv -csv v(in) v(out)
.endc
.end
""")
tr = rows("tr.csv")
uniform = tr is not None and all(len(r) == 3 for r in tr)
check("`.tran` CSV has a `time` scale header and uniform, parseable rows",
      tr is not None and tr[0] == ["time", "v(in)", "v(out)"] and uniform and
      len(tr) > 5, f"header={tr[0]} rows={len(tr)}" if tr else "no file")

# tidy
for f in ("_c.cir", "def.dat", "setvar.csv", "flag_first.csv", "flag_mid.csv",
          "flag_last.csv", "after.dat", "ac.csv", "tr.csv"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
