#!/usr/bin/env python3
"""
verify_lrmio.py -- verifies Enhancement-539, through the committed
openvaf-r + ngspice.

The 2026-09-02 LRM re-audit raised six findings; five were real and are fixed,
and each is pinned here. (The sixth -- "$random's seed never advances" -- was
withdrawn: it is a deliberate deviation for Newton convergence AND is already
reported by lint L019, which check [15] pins so the diagnostic cannot silently
disappear.)

  LRM 9.5.1  multichannel descriptors
  [1]  lrmio_mcd.va compiles
  [2]  $fopen(name) returns a ONE-HOT descriptor with bit 0 clear (bit 0 is
       reserved for stdout), and two of them differ
  [3]  OR-ing two multichannel descriptors writes to BOTH files
  [4]  each single descriptor writes to its own file only
  [5]  a $fopen(name, mode) file descriptor is disjoint from the mcd namespace
       (it has the most significant bit set) and writes to its own file

  LRM 9.5.1 / IEEE 1364  read-side semantics
  [6]  lrmio_read.va compiles
  [7]  $fclose then $fopen for reading restarts at byte 0
  [8]  $fscanf converts its fields (returns 2, iv=10, rv=1.5)
  [9]  $fscanf leaves the REMAINDER of the line for a following $fgets
  [10] ... and the $fgets after that gets the next line
  [11] $fgets + $sscanf does NOT reposition the descriptor (the $fgets
       legitimately consumed the whole line)

  LRM 9.4.4  %m
  [12] four instances of one module print four DISTINCT instance names, and a
       subcircuit instance's name is hierarchical

  LRM 3.6.1  nature abstol
  [13] a nature's declared abstol reaches the convergence test
  [14] an explicit `.option vntol` does not break that path (it takes
       precedence over the nature -- see Enhancement-539 -- and the deck must
       still solve)

  LRM 9.13.1  the withdrawn finding
  [15] a seeded RNG call inside a loop is reported by lint L019
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def compile_va(name):
    r = subprocess.run([OPENVAF, name], capture_output=True, text=True, cwd=HERE)
    return (r.returncode == 0 and
            os.path.exists(os.path.join(HERE, name.replace(".va", ".osdi"))),
            (r.stdout + r.stderr))

def run(deck_name, deck):
    with open(os.path.join(HERE, deck_name), "w") as f:
        f.write(deck)
    out = subprocess.run([NGSPICE, "-b", deck_name], capture_output=True,
                         text=True, cwd=HERE)
    return out.stdout + out.stderr

def opval(log, tag):
    m = re.search(rf"^{re.escape(tag)}\s*=\s*(-?[\d.eE+]+)", log, re.M)
    return float(m.group(1)) if m else None

def readfile(name):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return f.read()

ARTEFACTS = ["lrmio_mcd.osdi", "lrmio_read.osdi", "lrmio_m.osdi",
             "lrmio_nat.osdi", "_mcd.sp", "_read.sp", "_m.sp", "_nat.sp",
             "mcd_a.txt", "mcd_b.txt", "mcd_c.txt", "lrmio_data.txt",
             "_loop.va", "_loop.osdi", "lrmio_out.txt", "_nat2.sp"]
for f in ARTEFACTS:
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

# ---------------------------------------------------------------- 9.5.1 mcd --
ok, msg = compile_va("lrmio_mcd.va")
check("lrmio_mcd.va compiles", ok, msg.strip().splitlines()[0] if msg.strip() else "")

if ok:
    log = run("_mcd.sp",
              "* mcd\nv1 1 0 dc 1\nn1 1 0 m\n.model m lrmio_mcd\n"
              ".control\npre_osdi lrmio_mcd.osdi\nop\n"
              + "\n".join(f"echo {t} = $&@n1[{t}]" for t in
                          ["mA", "mB", "fd", "orv"])
              + "\n.endc\n.end\n")
    mA, mB, fd, orv = (opval(log, "mA"), opval(log, "mB"),
                       opval(log, "fd"), opval(log, "orv"))
    one_hot = (mA is not None and mB is not None
               and int(mA) > 0 and int(mB) > 0
               and int(mA) & (int(mA) - 1) == 0      # single bit set
               and int(mB) & (int(mB) - 1) == 0
               and int(mA) & 1 == 0                  # bit 0 reserved for stdout
               and int(mB) & 1 == 0
               and int(mA) != int(mB))
    check("$fopen(name) is one-hot with bit 0 clear, and distinct per file",
          one_hot and orv is not None and int(orv) == int(mA) | int(mB),
          f"mA={mA} mB={mB} mA|mB={orv}")

    a_txt, b_txt, c_txt = readfile("mcd_a.txt"), readfile("mcd_b.txt"), readfile("mcd_c.txt")
    check("OR-ed descriptors write to BOTH files",
          a_txt is not None and b_txt is not None
          and "BOTH" in a_txt and "BOTH" in b_txt,
          f"a={a_txt!r} b={b_txt!r}")
    check("each single descriptor writes to its own file only",
          a_txt is not None and b_txt is not None
          and "only-A" in a_txt and "only-A" not in b_txt
          and "only-B" in b_txt and "only-B" not in a_txt,
          f"a={a_txt!r} b={b_txt!r}")
    # A file descriptor lives in a disjoint namespace: the LRM gives it the
    # most significant bit, so as a signed 32-bit integer it reads negative.
    check("$fopen(name,mode) descriptor is disjoint from the mcd namespace",
          fd is not None and int(fd) < 0
          and c_txt is not None and "to-fd" in c_txt
          and "BOTH" not in c_txt,
          f"fd={fd} c={c_txt!r}")

# ------------------------------------------------------- 9.5.1 / 1364 reads --
with open(os.path.join(HERE, "lrmio_data.txt"), "w") as f:
    f.write("10 1.5 alpha\n20 2.5 beta\n30 3.5 gamma\n")

ok, msg = compile_va("lrmio_read.va")
check("lrmio_read.va compiles", ok, msg.strip().splitlines()[0] if msg.strip() else "")

if ok:
    log = run("_read.sp",
              "* read\nv1 1 0 dc 1\nn1 1 0 m\n.model m lrmio_read\n"
              ".control\npre_osdi lrmio_read.osdi\nop\n"
              + "\n".join(f"echo {t} = $&@n1[{t}]" for t in
                          ["nf", "iv", "rv"])
              + "\n.endc\n.end\n")
    # Strings are not readable as operating-point variables, so the model
    # writes them to a file (the same idiom stringio_examples uses).
    rep = readfile("lrmio_out.txt") or ""
    def field(tag):
        # $fgets keeps the trailing newline, so the value spans to the "]".
        m = re.search(rf"^{re.escape(tag)}=\[(.*?)\]$", rep, re.M | re.S)
        return m.group(1) if m else None
    check("$fclose + $fopen for reading restarts at byte 0",
          (field("reopen_first") or "").startswith("10 1.5 alpha"),
          f"got {field('reopen_first')!r}")
    check("$fscanf converts its fields (2, 10, 1.5)",
          opval(log, "nf") == 2 and opval(log, "iv") == 10
          and opval(log, "rv") == 1.5,
          f"nf={opval(log,'nf')} iv={opval(log,'iv')} rv={opval(log,'rv')}")
    rest = field("scan_rest") or ""
    check("$fscanf leaves the remainder of the line for $fgets",
          "alpha" in rest and "20" not in rest, f"got {rest!r}")
    check("the $fgets after that reads the next line",
          (field("scan_next") or "").startswith("20 2.5 beta"),
          f"got {field('scan_next')!r}")
    check("$fgets + $sscanf does NOT reposition the descriptor",
          (field("ss_next") or "").startswith("20 2.5 beta"),
          f"got {field('ss_next')!r}")

# ------------------------------------------------------------------ 9.4.4 %m --
ok, msg = compile_va("lrmio_m.va")
check("lrmio_m.va compiles", ok, msg.strip().splitlines()[0] if msg.strip() else "")

if ok:
    log = run("_m.sp",
              "* %m\n.subckt leg p\nnsub p 0 m\n.ends\n"
              "v1 1 0 dc 1\nna 1 0 m\nnb 1 0 m\nx1 1 leg\nx2 1 leg\n"
              ".model m lrmio_m\n"
              ".control\npre_osdi lrmio_m.osdi\nop\nquit\n.endc\n.end\n")
    names = set(re.findall(r"WHOAMI (\S+)", log))
    check("%m prints four DISTINCT instance names, hierarchical in a subckt",
          len(names) == 4 and any("." in n for n in names)
          and "lrmio_m" not in names,
          f"got {sorted(names)}")

# ------------------------------------------------------------ 3.6.1 abstol --
ok, msg = compile_va("lrmio_nat.va")
check("lrmio_nat.va compiles", ok, msg.strip().splitlines()[0] if msg.strip() else "")

if ok:
    log = run("_nat.sp",
              "* nature abstol\nv1 1 0 dc 1\nn1 1 0 m\n.model m lrmio_nat\n"
              ".control\npre_osdi lrmio_nat.osdi\nset ngdebug\nop\n"
              "echo vv = $&@n1[vv]\n.endc\n.end\n")
    tols = [float(x) for x in
            re.findall(r"convergence abstol = ([\d.eE+-]+)", log)]
    # 1e-9 is the declared potential tolerance; it must reach the solver, and
    # the operating point must still be correct.
    check("a nature's declared abstol reaches the convergence test",
          any(abs(t - 1e-9) < 1e-18 for t in tols) and opval(log, "vv") == 1.0,
          f"tolerances seen: {tols}, vv={opval(log, 'vv')}")

    # An explicit .option must beat the nature: disciplines.vams declares
    # abstol on the STANDARD natures too, so without this a user who loosened
    # vntol to get a stubborn circuit to converge would be silently pulled
    # back to the discipline's value. Both decks must still solve correctly,
    # and the setup-time report must show the nature was read in both.
    log2 = run("_nat2.sp",
               "* nature abstol vs user option\n.options vntol=1e-4\n"
               "v1 1 0 dc 1\nn1 1 0 m\n.model m lrmio_nat\n"
               ".control\npre_osdi lrmio_nat.osdi\nset ngdebug\nop\n"
               "echo vv = $&@n1[vv]\n.endc\n.end\n")
    check("an explicit .option vntol does not break the nature path",
          opval(log2, "vv") == 1.0
          and "convergence abstol" in log2,
          f"vv={opval(log2, 'vv')}")

# ----------------------------------------------------- 9.13.1 the withdrawal --
# The audit called the pure RNG seed an undiagnosed silent defect. It is
# neither: it is deliberate (an advancing seed would change on every Newton
# iteration and break convergence) and it is reported. Pin the diagnostic so
# the property the audit was actually right to care about cannot regress.
with open(os.path.join(HERE, "_loop.va"), "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module _loop(a, b);\n  inout a, b;\n  electrical a, b;\n"
            "  integer s, i;\n  real x;\n"
            "  analog begin\n    @(initial_step) begin\n      s = 5;\n"
            "      for (i = 0; i < 5; i = i + 1)\n"
            "        x = $rdist_uniform(s, 0.0, 1.0);\n    end\n"
            "    I(a, b) <+ V(a, b) * 1e-6;\n  end\nendmodule\n")
r = subprocess.run([OPENVAF, "_loop.va"], capture_output=True, text=True, cwd=HERE)
diag = r.stdout + r.stderr
check("a seeded RNG call inside a loop is reported (lint L019)",
      "L019" in diag and "same number every iteration" in diag,
      diag.strip().splitlines()[0] if diag.strip() else "no diagnostic")

for f in ARTEFACTS:
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
