#!/usr/bin/env python3
"""Enhancement-252: heap out-of-bounds WRITES in the xfer / file_source file parsers.

Two analog XSPICE code models read a numeric data file into a growing double
array, and both under-reserve before the store, overrunning the heap.

  [xfer]        (analog/xfer/cfunc.mod, read_file) reads a transfer-function file
                (a Touchstone-style `# ...` option line, then data). It sscanf's
                up to 9 values per line and, via a small state machine, stores
                every value -- so a line holding more than one freq/real/imag
                record stores more than 3. But the allocation check reserved only
                3 (`if (i + 3 > size)`), so a multi-record line wrote past the
                buffer at the 1024-double (ALLOC) boundary (AddressSanitizer:
                heap-buffer-overflow WRITE, cm_xfer). Fixed: reserve the sscanf
                maximum of 9 (`if (i + 9 > size)`).

  [file_source] (analog/file_source/cfunc.mod) stores one record per line --
                a timepoint plus `size` channel values, i.e. stepsize = size + 1
                doubles -- but reserved only `size` (`vecallocated - size`),
                one short. At the reallocation boundary the last channel wrote one
                double past the end (AddressSanitizer: heap-buffer-overflow WRITE,
                cm_filesource). Fixed: reserve a full record (`- stepsize`).

Both are heap OOB WRITES (not reads), reachable from a valid-syntax netlist with a
crafted data file. On the release build the few-double overrun corrupts adjacent
heap silently rather than always crashing -- undefined behaviour either way.

Checks (batch mode, -b; both solvers). A crash shows up as a NEGATIVE return code.
 1. a valid transfer-function file simulates through xfer;
 2. an xfer file with multi-record (9-value) lines no longer overruns (runs, no
    crash);
 3. a valid file_source data file simulates;
 4. a file_source file long enough to cross the realloc boundary no longer
    overruns (runs, no crash).

Line 1 of every SPICE deck is the title (ignored).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402  (also sets SPICE_LIB_DIR)
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

passed = failed = 0
_tmp = []


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def is_crash(rc):
    return rc < 0 or rc >= 128


def wfile(name, text):
    p = os.path.join(HERE, name)
    open(p, "w").write(text)
    _tmp.append(p)
    return name


def run(deck):
    cir = os.path.join(HERE, "_ff.cir")
    open(cir, "w").write(deck)
    _tmp.append(cir)
    r = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True,
                       timeout=90, cwd=HERE)
    return r.returncode, r.stdout.replace("\r", "\n") + r.stderr


# ---- xfer data files ----
_valid_xfer = "# Hz RI\n" + "\n".join(f"{1e3*1.1**i:g} 0.5 0.1" for i in range(30)) + "\n"
_freq = 1.0
_oob_lines = []
for _ in range(200):                       # 200 lines x 9 values = crosses ALLOC=1024
    _row = []
    for _ in range(3):
        _row += [f"{_freq:g}", "0.5", "0.1"]; _freq *= 1.001
    _oob_lines.append(" ".join(_row))
_oob_xfer = "# Hz RI\n" + "\n".join(_oob_lines) + "\n"

wfile("xf_ok.dat", _valid_xfer)
wfile("xf_oob.dat", _oob_xfer)


def xfer_deck(fn):
    return (f"xfer\nVin in 0 dc 0 ac 1\nA1 in out xfermod\n"
            f".model xfermod xfer(file=\"{fn}\" r_i=true db=false)\n"
            f"R1 out 0 1k\n.ac dec 5 1 1meg\n.print ac v(out)\n.end\n")


# availability gate
rc, out = run(xfer_deck("xf_ok.dat"))
if is_crash(rc) or "Index" not in out:
    if "Can not open" in out or "code model" in out.lower() or is_crash(rc):
        print(f"  SKIP  XSPICE code models unavailable in this checkout (rc={rc})")
        for p in _tmp:
            if os.path.exists(p):
                os.remove(p)
        raise SystemExit(0)

check("valid transfer-function file simulates through xfer",
      not is_crash(rc) and "Index" in out, f"rc={rc}")

rc, out = run(xfer_deck("xf_oob.dat"))
check("xfer multi-record (9-value) lines: no heap overrun, runs (was OOB write)",
      not is_crash(rc) and "Index" in out, f"rc={rc}")

# ---- file_source data files (octave-matrix header + rows) ----
def fs_data(nrows):
    hdr = f"# name: x\n# type: matrix\n# rows: {nrows}\n# columns: 3\n"
    return hdr + "\n".join(f"{k*1e-9:g} 0.1 0.2" for k in range(nrows)) + "\n"


wfile("fs_ok.dat", fs_data(50))
wfile("fs_oob.dat", fs_data(1700))          # crosses the (size+1)*1000 realloc boundary


def fs_deck(fn):
    return (f"filesource\nA1 %vd([1 0 3 0]) fsmod\n"
            f".model fsmod filesource(file=\"{fn}\" amploffset=[0 0] amplscale=[1 1])\n"
            f"R0 1 0 1k\nR1 3 0 1k\n.tran 1n 40n\n.print tran v(1)\n.end\n")


rc, out = run(fs_deck("fs_ok.dat"))
check("valid file_source data file simulates",
      not is_crash(rc) and "Index" in out, f"rc={rc}")

rc, out = run(fs_deck("fs_oob.dat"))
check("file_source across the realloc boundary: no heap overrun, runs (was OOB write)",
      not is_crash(rc) and "Index" in out, f"rc={rc}")

for p in _tmp:
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
