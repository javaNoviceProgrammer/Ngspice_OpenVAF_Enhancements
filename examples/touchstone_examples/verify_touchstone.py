#!/usr/bin/env python3
"""
verify_touchstone.py -- verifies Enhancement-64: Touchstone export from the
.sp analysis, end-to-end through the committed openvaf-r + ngspice.

Enhancement-63 found `wrs2p` unusable out of the box (it demanded a vector
named Rbase that nothing created) and hardwired to 2 ports. Enhancement-64:

  * the .sp analysis now PUBLISHES `Rbase` (the ports' reference
    resistance, read from port 1's z0) into its plot, so wrs2p works with
    no manual `let Rbase = ...`; a user-defined `let Rbase` still
    overrides; the reader handles the plot's complex data robustly.
  * NEW `wrsnp` command (wrs2p dispatches to it too for N != 2): writes a
    Touchstone v1 .sNp for ANY port count -- N >= 3 in row-major order
    with at most four complex pairs per data line and each matrix row on
    its own line, per the Touchstone 1.x spec; a 1-port is one pair per
    line. The classic 2-port S11 S21 S12 S22 column order is preserved
    through the original writer.
  * 1-port .sp analyses (reflection measurements) are now possible at all:
    the old hard error was over-strict, and the complex-matrix cadjoint()
    had no 1x1 base case -- its cofactor loop allocated negative-sized
    minors and ngspice died with "malloc: can't allocate -8 bytes". The
    adjugate of [a] is [1], making cinverse of a 1x1 equal 1/a.

Round 2 (Enhancement-72) adds output options and a READER:
  * `wrsnp <file> [ri|ma|db] [s|y|z] [hz|khz|mhz|ghz]` -- MA (magnitude/
    angle-degrees) and DB (20*log10/angle) formats, Y-/Z-parameter export
    (normalized to Rbase per the Touchstone v1 spec), and kHz/MHz/GHz
    frequency units, all reflected in the option line;
  * `rdsnp <file> [nports]` -- reads a Touchstone v1 file (any format,
    unit, parameter type, port count; 2-port column order handled) into a
    new plot holding a Hz `frequency` scale plus complex vectors matching
    the .sp plot conventions, so measured data compares 1:1 against
    simulation. Round-trip write-MA -> read -> compare is pinned below.

Enhancement-744 (Touchstone-import hunt F3, with F4's message and F8): the
reader is version-aware. A Touchstone 2 keyword line was dropped whole (sscanf
stops at the '['), so `[Two-Port Data Order] 12_21` was never seen and S12/S21
came back swapped, `[Reference]` was lost and a v2 Y/Z file would have been
de-normalized as v1. Now the keywords are read (per-port [Reference] published
as the vector Zref, [Matrix Format] Lower/Upper mirrored, an information block
skipped, [Noise Data]/[End] ending the data), [Mixed-Mode Order] and the G/H
types are refused by name, a count that is not a whole number of frames names
the count and the v1 noise-parameter rows as the usual cause, a v2 Y/Z file is
absolute and a v1 one de-normalized, the port count comes from a .yNp/.zNp
extension too, and a file with no option line takes the specification's default
GHz S MA R 50 (this reader assumed Hz S RI). Section [9] pins each.
Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_va(src):
    osdi = os.path.splitext(src)[0] + ".osdi"
    out = os.path.join(HERE, osdi)
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run([OPENVAF, src, "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr, os.path.exists(out)


def run_deck(name, deck):
    with open(os.path.join(HERE, name), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", name],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr


def read_touchstone(name):
    """Returns (option_line, blocks) where blocks[freq] = flat list of
    (re, im) pairs in file order."""
    option = None
    freqs = []
    data = []
    for line in open(os.path.join(HERE, name)):
        line = line.strip()
        if not line or line.startswith("!"):
            continue
        if line.startswith("#"):
            option = line
            continue
        vals = [float(x) for x in line.split()]
        # a new frequency block has an odd count (freq + pairs)
        if len(vals) % 2 == 1:
            freqs.append(vals[0])
            data.append([])
            vals = vals[1:]
        pairs = list(zip(vals[0::2], vals[1::2]))
        data[-1].extend(pairs)
    return option, list(zip(freqs, data))


def ports(n):
    return "".join(f"V{k} p{k} 0 DC 0 AC 1 portnum {k} z0 50\n" for k in range(1, n + 1))


def star(n):
    return "".join(f"N{k} p{k} star mm\n" for k in range(1, n + 1)) + ".model mm ores r=50\n"


out, ok = compile_va("ts_blocks.va")
if not ok:
    check("blocks compile", False, out.splitlines()[0] if out else "")
    raise SystemExit(1)

print("[1] wrs2p works with NO manual Rbase (auto from port z0)")
log = run_deck("_t2.cir", """* auto rbase
.control
pre_osdi ts_blocks.osdi
.endc
V1 in 0 DC 0 AC 1 portnum 1 z0 50
N1 in out mm
.model mm ores r=100
N2 out 0 mmc
.model mmc ocap cap=1n
V2 out 0 DC 0 AC 1 portnum 2 z0 50
.sp dec 1 1meg 100meg
.control
run
wrs2p _rc.s2p
set numdgt=10
print S_2_1
.endc
.end
""")
check("no Rbase error", "No Rbase vector" not in log and os.path.exists(os.path.join(HERE, "_rc.s2p")))
option, blocks = read_touchstone("_rc.s2p")
check("header: # Hz S RI R 50", option is not None and re.match(r"#\s*Hz\s+S\s+RI\s+R\s+50\b", option),
      f"({option})")
# 2-port order S11 S21 S12 S22: compare S21 in the file against the plot
plot_s21 = re.findall(r"^\d+\s+[0-9.eE+-]+\s+(-?[0-9.eE+-]+),\s+(-?[0-9.eE+-]+)", log, re.M)
ok21 = len(blocks) == 3 and len(plot_s21) == 3
for (f, pairs), (pre, pim) in zip(blocks, plot_s21):
    ok21 = ok21 and abs(pairs[1][0] - float(pre)) < 1e-6 and abs(pairs[1][1] - float(pim)) < 1e-6
check("file S21 (2nd pair, Touchstone 2-port order) == plot S_2_1", ok21)

print("[1b] wrsnp on a 2-port == wrs2p (same handler, same file)")
run_deck("_talias.cir", """* alias identity
.control
pre_osdi ts_blocks.osdi
.endc
V1 in 0 DC 0 AC 1 portnum 1 z0 50
N1 in out mm
.model mm ores r=100
V2 out 0 DC 0 AC 1 portnum 2 z0 50
.sp lin 3 1meg 3meg
.control
run
wrs2p _a.s2p
wrsnp _b.s2p
.endc
.end
""")
a = [l for l in open(os.path.join(HERE, "_a.s2p")) if not l.startswith("!Generated")]
b = [l for l in open(os.path.join(HERE, "_b.s2p")) if not l.startswith("!Generated")]
check("byte-identical output (modulo timestamp)", a == b and len(a) > 4)

print("[2] a user-defined `let Rbase` still overrides")
run_deck("_tov.cir", """* rbase override
.control
pre_osdi ts_blocks.osdi
.endc
V1 in 0 DC 0 AC 1 portnum 1 z0 50
N1 in out mm
.model mm ores r=100
V2 out 0 DC 0 AC 1 portnum 2 z0 50
.sp lin 1 1meg 1meg
.control
run
let Rbase = 75
wrs2p _ov.s2p
.endc
.end
""")
option, _ = read_touchstone("_ov.s2p")
check("header honors let Rbase = 75", option is not None and " R 75" in option, f"({option})")

print("[3] 1-port .sp + wrsnp .s1p (was a hard error, then a malloc crash)")
log = run_deck("_t1.cir", """* 1-port reflection
.control
pre_osdi ts_blocks.osdi
.endc
V1 p1 0 DC 0 AC 1 portnum 1 z0 50
N1 p1 0 mm
.model mm ores r=100
.sp lin 1 1meg 1meg
.control
run
wrsnp _load.s1p
.endc
.end
""")
check("1-port analysis runs (no crash)", "can't allocate" not in log and "at least two" not in log)
option, blocks = read_touchstone("_load.s1p")
check("S11 == (100-50)/(100+50) == 1/3 exactly",
      len(blocks) == 1 and len(blocks[0][1]) == 1
      and abs(blocks[0][1][0][0] - 1.0/3) < 1e-6 and abs(blocks[0][1][0][1]) < 1e-9)

print("[4] wrsnp .s3p: row-major layout, star values exact")
run_deck("_t3.cir", f"""* 3-port star
.control
pre_osdi ts_blocks.osdi
.endc
{ports(3)}{star(3)}.sp lin 3 1meg 3meg
.control
run
wrsnp _star.s3p
.endc
.end
""")
option, blocks = read_touchstone("_star.s3p")
ok3 = (option is not None and " R 50" in option and len(blocks) == 3
       and all(len(pairs) == 9 for _, pairs in blocks)
       and all(abs(re_ - 1.0/3) < 1e-6 and abs(im) < 1e-9
               for _, pairs in blocks for re_, im in pairs))
check("3 freq blocks x 9 pairs, all == 1/3 (star)", ok3)
# row-major: each of the 3 matrix rows on its own line
lines = [l for l in open(os.path.join(HERE, "_star.s3p"))
         if l.strip() and not l.strip().startswith(("!", "#"))]
check("each matrix row on its own line (9 data lines)", len(lines) == 9, f"({len(lines)} lines)")

print("[5] wrsnp .s5p: rows wrap at 4 pairs per line")
run_deck("_t5.cir", f"""* 5-port star
.control
pre_osdi ts_blocks.osdi
.endc
{ports(5)}{star(5)}.sp lin 1 1meg 1meg
.control
run
wrsnp _star.s5p
.endc
.end
""")
option, blocks = read_touchstone("_star.s5p")
ok5 = (len(blocks) == 1 and len(blocks[0][1]) == 25
       and all(abs(re_ - 0.2) < 1e-6 for re_, _ in blocks[0][1]))
check("25 pairs, all == 1/5 (star)", ok5)
lines = [l for l in open(os.path.join(HERE, "_star.s5p"))
         if l.strip() and not l.strip().startswith(("!", "#"))]
check("5 rows x 2 lines (wrap at 4 pairs) == 10 data lines", len(lines) == 10,
      f"({len(lines)} lines)")

print("[6] round 2: MA/DB formats + frequency units (headers + math)")
log = run_deck("_t6.cir", """* round2 formats
.control
pre_osdi ts_blocks.osdi
.endc
V1 in 0 DC 0 AC 1 portnum 1 z0 50
N1 in out mm
.model mm ores r=100
N2 out 0 mmc
.model mmc ocap cap=1n
V2 out 0 DC 0 AC 1 portnum 2 z0 50
.sp dec 1 1meg 100meg
.control
run
wrsnp _r2.s2p
wrsnp _r2ma.s2p ma
wrsnp _r2db.s2p db ghz
wrsnp _r2y.y2p y
wrsnp _r2z.z2p z mhz
.endc
.end
""")
opt_ma, blocks_ma = read_touchstone("_r2ma.s2p")
opt_db, blocks_db = read_touchstone("_r2db.s2p")
opt_y, _ = read_touchstone("_r2y.y2p")
opt_z, _ = read_touchstone("_r2z.z2p")
_, blocks_ri = read_touchstone("_r2.s2p")
check("option lines: MA, DB+GHz, Y, Z+MHz",
      " S MA R 50" in (opt_ma or "") and opt_db is not None
      and opt_db.startswith("# GHz") and " DB R 50" in opt_db
      and " Y RI R 50" in (opt_y or "") and opt_z is not None
      and opt_z.startswith("# MHz") and " Z RI R 50" in opt_z)
# MA pair 0 (S11) must equal the RI pair 0 in polar form
ri = blocks_ri[0][1][0]
ma = blocks_ma[0][1][0]
check("MA magnitude/angle == polar(RI)",
      abs(ma[0] - math.hypot(*ri)) < 1e-5
      and abs(ma[1] - math.degrees(math.atan2(ri[1], ri[0]))) < 1e-3)
db = blocks_db[0][1][0]
check("DB == 20*log10(mag), freq in GHz",
      abs(db[0] - 20 * math.log10(math.hypot(*ri))) < 1e-4
      and abs(blocks_db[0][0] - 1e-3) < 1e-9)

print("[7] round 2: rdsnp reader round-trip (write MA -> read -> compare)")
log = run_deck("_t7.cir", """* roundtrip
.control
pre_osdi ts_blocks.osdi
.endc
V1 in 0 DC 0 AC 1 portnum 1 z0 50
N1 in out mm
.model mm ores r=100
N2 out 0 mmc
.model mmc ocap cap=1n
V2 out 0 DC 0 AC 1 portnum 2 z0 50
.sp dec 1 1meg 100meg
.control
run
set numdgt=10
let s21sim = S_2_1
wrsnp _rt.s2p ma
rdsnp _rt.s2p
let din = maximum(mag(S_2_1 - {sp1}.s21sim))
print din
.endc
.end
""")
m = re.search(r"din = ([0-9.eE+-]+)", log)
check("max |S21(read) - S21(sim)| below the file precision (1e-6)",
      m is not None and float(m.group(1)) < 1e-6,
      f"({m.group(1) if m else '?'})")
check("reader announces the import",
      "read from _rt.s2p" in log)

print("[8] round 2: rdsnp of a hand-written 'measured' file")
with open(os.path.join(HERE, "_meas.s2p"), "w") as fh:
    fh.write("""! hand-written measurement-style file
# MHz S MA R 50
1.0   0.5 0.0    0.5 -90.0   0.5 -90.0   0.5 180.0
2.0   0.4 10.0   0.6 -80.0   0.6 -80.0   0.4 170.0
""")
log = run_deck("_t8.cir", """* read measured
.control
rdsnp _meas.s2p
set numdgt=10
print frequency[0] frequency[1]
print S_1_1 S_2_1
.endc
.end
""")
f0 = re.search(r"frequency\[0\] = ([0-9.eE+-]+)", log)
rows = re.findall(r"^\d+\s+(-?[0-9.eE+-]+),\s+(-?[0-9.eE+-]+)\s+(-?[0-9.eE+-]+),\s+(-?[0-9.eE+-]+)", log, re.M)
ok8 = (f0 is not None and abs(float(f0.group(1)) - 1e6) < 1e-3   # MHz -> Hz
       and len(rows) == 2
       and abs(float(rows[0][0]) - 0.5) < 1e-9                    # S11 = 0.5 at 0 deg
       and abs(float(rows[0][1])) < 1e-9
       and abs(float(rows[0][2])) < 1e-9                          # S21 = 0.5 at -90 deg
       and abs(float(rows[0][3]) + 0.5) < 1e-9)                   #      -> -0.5j
check("MHz scale + MA->RI conversion + 2-port column order", ok8,
      f"({len(rows)} rows)")

print("[9] Enhancement-744: rdsnp reads Touchstone 2; the v1 noise rows, the no-option-line default")


def rd(name, text, ctl, tag):
    with open(os.path.join(HERE, name), "w") as fh:
        fh.write(text)
    return run_deck(f"_t9{tag}.cir", f"* rdsnp {name}\n.control\n{ctl}\nset numdgt=10\n.endc\n.end\n")


def cx(log, name, k=0):
    m = re.search(r"^" + re.escape(name) + r"\[" + str(k) + r"\] = (-?[0-9.eE+-]+),\s*(-?[0-9.eE+-]+)", log, re.M | re.I)
    return complex(float(m.group(1)), float(m.group(2))) if m else None


def val(log, expr):
    m = re.search(r"^" + re.escape(expr) + r" = (-?[0-9.eE+-]+)", log, re.M | re.I)
    return float(m.group(1)) if m else None


# a non-reciprocal 2-port (S12 = 0.1*S21) so the two directions can be told apart
V2 = """[Version] 2.0
# Hz S MA
[Number of Ports] 2
[Two-Port Data Order] 12_21
[Number of Frequencies] 2
[Reference] 50
   75
[Begin Information]
  1.5 2.5 3.5  numbers that are not data
[End Information]
[Network Data]
1e6  0.3 0.0   0.05 -90.0   0.5 -90.0   0.4 180.0
2e6  0.2 10.0  0.06 -80.0   0.6 -80.0   0.3 170.0
[Noise Data]
1e6 2.0 0.3 20 0.5
[End]
"""
log = rd("_v2.s2p", V2, "rdsnp _v2.s2p\nprint S_2_1[0] S_1_2[0] Rbase Zref[0] Zref[1] length(frequency)", "a")
s21, s12 = cx(log, "S_2_1"), cx(log, "S_1_2")
check("a v2 two-port in 12_21 order: S21 = 0.5 at -90 deg and S12 = 0.05 at -90 deg, not swapped; announced as Touchstone 2",
      s21 is not None and s12 is not None and abs(s21 - (-0.5j)) < 1e-9 and abs(s12 - (-0.05j)) < 1e-9
      and "(Touchstone 2)" in log, f"(S21={s21} S12={s12})")
check("[Reference] 50 / 75 over two lines: Rbase is port 1's 50, Zref = [50, 75], the note about per-port references; "
      "the information block and the [Noise Data] section are skipped, 2 points",
      val(log, "Rbase") == 50.0 and val(log, "Zref[0]") == 50.0 and val(log, "Zref[1]") == 75.0
      and val(log, "length(frequency)") == 2.0 and "gives every port its own reference impedance" in log, log[-300:])
Y2 = "[Version] 2.0\n# Hz Y RI\n[Number of Ports] 2\n[Two-Port Data Order] 12_21\n[Network Data]\n1e6 0.02 0 -0.02 0 -0.02 0 0.02 0\n2e6 0.02 0 -0.02 0 -0.02 0 0.02 0\n[End]\n"
Y1 = "# Hz Y RI R 50\n1e6 1.0 0 -1.0 0 -1.0 0 1.0 0\n2e6 1.0 0 -1.0 0 -1.0 0 1.0 0\n"
log = rd("_v2y.s2p", Y2, "rdsnp _v2y.s2p\nprint Y_1_1[0]", "b")
y2 = cx(log, "Y_1_1")
log1 = rd("_v1y.y2p", Y1, "rdsnp _v1y.y2p\nprint Y_1_1[0]", "c")
y1 = cx(log1, "Y_1_1")
check("a v2 Y file is absolute (Y11 = 0.02 S as written); a v1 .y2p carries Y*R and is de-normalized to the same 0.02 S -- "
      "and its port count comes from the .y2p extension",
      y2 is not None and y1 is not None and abs(y2 - 0.02) < 1e-12 and abs(y1 - 0.02) < 1e-12 and "cannot infer" not in log1,
      f"(v2 {y2}, v1 {y1})")
TS3 = "[Version] 2.0\n# GHz S RI R 50\n[Number of Ports] 3\n[Matrix Format] Lower\n[Network Data]\n1 0.1 0  0.2 0 0.3 0  0.4 0 0.5 0 0.6 0\n2 0.1 0  0.2 0 0.3 0  0.4 0 0.5 0 0.6 0\n[End]\n"
log = rd("_v2low.ts", TS3, "rdsnp _v2low.ts\nprint S_1_2[0] S_2_1[0] S_3_1[0] S_3_3[0] frequency[0]", "d")
check("a 3-port .ts in [Matrix Format] Lower: the triangle mirrored (S12 = S21 = 0.2, S31 = 0.4, S33 = 0.6), the port count from "
      "[Number of Ports], GHz scaled",
      cx(log, "S_1_2") == 0.2 and cx(log, "S_2_1") == 0.2 and cx(log, "S_3_1") == 0.4 and cx(log, "S_3_3") == 0.6
      and val(log, "frequency[0]") == 1e9, log[-200:])
V1N = "# MHz S MA R 50\n1.0 0.5 0.0 0.5 -90.0 0.5 -90.0 0.5 180.0\n2.0 0.4 10.0 0.6 -80.0 0.6 -80.0 0.4 170.0\n! noise parameters\n1.0 2.0 0.30 20 0.5\n2.0 2.5 0.35 40 0.6\n"
log = rd("_v1n.s2p", V1N, "rdsnp _v1n.s2p", "e")
check("a v1 file with noise-parameter rows after the network data is refused naming the count, the frame size and the rows "
      "(it said 'wrong port count?')",
      "28 numbers of network data, not a whole number of 2-port frames of 9" in log and "noise-parameter rows" in log, log[-300:])
NOOPT = "1.0   0.5 0.0    0.5 -90.0   0.5 -90.0   0.5 180.0\n2.0   0.4 10.0   0.6 -80.0   0.6 -80.0   0.4 170.0\n"
log = rd("_noopt.s2p", NOOPT, "rdsnp _noopt.s2p\nprint frequency[0] S_2_1[0]", "f")
s21 = cx(log, "S_2_1")
check("no option line: the specification's default GHz S MA R 50 -- frequency[0] = 1e9, S21 = 0.5 at -90 deg = -0.5j "
      "(the reader assumed Hz S RI: 1 Hz and 0.5-90j)",
      val(log, "frequency[0]") == 1e9 and s21 is not None and abs(s21 - (-0.5j)) < 1e-9 and "GHz S MA R 50" in log, f"(f0={val(log, 'frequency[0]')} S21={s21})")
MM = V2.replace("[Network Data]", "[Mixed-Mode Order] D1,2 C1,2\n[Network Data]")
NOORD = V2.replace("[Two-Port Data Order] 12_21\n", "")
la = rd("_mm.s2p", MM, "rdsnp _mm.s2p", "g")
lb = rd("_noord.s2p", NOORD, "rdsnp _noord.s2p", "h")
lc = rd("_v2b.s2p", V2, "rdsnp _v2b.s2p 3", "i")
check("refused by name: [Mixed-Mode Order]; a v2 two-port without [Two-Port Data Order]; a [Number of Ports] that disagrees with the count on the command",
      "Mixed-Mode Order" in la and "without [Two-Port Data Order]" in lb and "disagrees with the 3 given on the command" in lc,
      (la + lb + lc)[-300:])

print(f"\n{'ALL PASS' if failed == 0 else 'FAILURES'}: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
