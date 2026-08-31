#!/usr/bin/env python3
"""Enhancement-516: the display and file-I/O system tasks, audited against
Accellera VAMS-2023 clauses 9.4 and 9.5, then fixed.

The headline is LRM 9.4.6 -- "All the display tasks, except $debug, shall not
display output unless an iteration has been accepted" -- and its file-side
sibling 9.5.9 ("file write operations shall not be performed unless the
iteration is accepted"). Every display task fired on every Newton iteration: a
single .op printed FIFTEEN $strobe lines walking through the unconverged
iterates, and an un-gated $fdisplay wrote five lines to its file, the first
holding v=0 -- a value the circuit never settled at. Output is now buffered per
iteration and flushed when the point is ACCEPTED (transient accept, analysis
end, each .dc sweep point); statements inside event-controlled blocks fire on
the event's own iteration and are tagged to print immediately, so
@(initial_step) logging is byte-for-byte what it always was.

Also pinned here, each against its clause:

  * 9.4.1 -- $monitor prints only "if a variable or expression in the argument
    list changes value compared with the last accepted step". It had NO change
    detection at all (120 lines over a transient whose watched value changed
    once). Now: one line per change. A $abstime argument in the text defeats
    the comparison -- documented deviation.
  * 9.4.3 -- %r/%R engineering notation printed GARBAGE for every input
    (natural log for the scale pick, an unapplied table offset, and the scale
    character's POINTER handed to %c). Now 1e3 -> `1.000000k`, 1e-9 ->
    `1.000000n`, 0.036 -> `36.000000m`, 2.2e4 -> `22.000000k`.
  * 9.4.1 (IEEE 1364 17.1.1.2) -- a null argument, two adjacent commas,
    produces a single space; it was a compile-time type error.
  * 9.5.1.1 -- "content written from the following analyses shall be appended
    to the content written during the previous analyses": a "w" reopen in the
    same simulator process appends now (it truncated, so only the last
    analysis's output survived).
  * 9.5 lifecycle -- the open-write-close idiom in the main analog body used
    to write NOTHING (the descriptor was closed by hoisted init code before
    eval's first write); an instance-setup $fclose now defers to the first
    accepted flush. And ngspice re-runs the instance initialization (setup +
    temperature), so a re-run re-opens fresh instead of appending a second
    copy -- the $rewind/$fseek overwrite file must hold EXACTLY 'XY234**789'.
  * 9.5.1 -- the pre-opened descriptor 32'h8000_0001 reaches stdout (and
    'h8000_0002 stderr).
"""

import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_ls_") or junk.startswith("lrmsysio_") and (
                junk.endswith(".txt") or junk.endswith(".osdi")):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_file(name):
    osdi = os.path.join(HERE, f"_ls_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_ls_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmsysio\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
                f"option noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def rmfiles(*names):
    for n in names:
        try:
            os.remove(os.path.join(HERE, n))
        except OSError:
            pass


DIODE_DECK = "V1 in 0 DC 1.0\nR1 in a 1k\nN1 a 0 mm\n.model mm lrmsysio()"

# ---- 9.4.6: accepted iterations only ---------------------------------------
print("lrmsysio.va (a diode: the .op needs many Newton iterations):")
rc, out, osdi = compile_file("lrmsysio.va")
check("[1] compiles (incl. the null display argument)", rc == 0,
      out.strip().splitlines()[-1] if rc else "")
if rc == 0:
    rmfiles("lrmsysio_op.txt")
    op = run(DIODE_DECK, "op", "op", osdi)
    n_strobe = len(re.findall(r"STROBE v=", op))
    n_disp = len(re.findall(r"DISPLAY v=", op))
    n_debug = len(re.findall(r"DEBUG v=", op))
    n_gated = len(re.findall(r"GATED once", op))
    check("[2] $strobe printed once for the accepted .op point (LRM 9.4.6)",
          n_strobe == 1, f"{n_strobe} line(s)")
    check("[3] $display printed once as well", n_disp == 1, f"{n_disp}")
    check("[4] $debug is the clause's exemption: still one line per iteration",
          n_debug > 2, f"{n_debug} iterations seen")
    check("[5] @(initial_step) output printed exactly once (event-gated, immediate)",
          n_gated == 1, f"{n_gated}")
    m = re.search(r"STROBE v=([-+0-9.eE]+)", op)
    check("[6] the printed value is the CONVERGED one, not an early iterate",
          m is not None and abs(float(m.group(1)) - 0.55) < 0.2,
          m.group(1) if m else "no line")

    # 9.5.9: the un-gated $fdisplay wrote through the deferral
    fpath = os.path.join(HERE, "lrmsysio_op.txt")
    lines = open(fpath).read().splitlines() if os.path.exists(fpath) else None
    check("[7] un-gated $fdisplay: ONE line for the .op (writes deferred, 9.5.9)",
          lines is not None and len(lines) == 1, f"{lines}")
    mfile = re.search(r"CONVERGED v=([-+0-9.eE]+)", lines[0]) if lines else None
    check("[8] ... and it holds the converged voltage, not an unconverged iterate",
          m is not None and mfile is not None and
          abs(float(mfile.group(1)) - float(m.group(1))) < 1e-4,
          lines[0] if lines else "")

    # 9.4.1: $monitor change detection over a transient
    tr = run(DIODE_DECK.replace("DC 1.0", "DC 1.0 PULSE(1 1.2 0.6 1n 1n 1 2)"),
             "tran 0.01 1", "tran", osdi)
    n_mon = len(re.findall(r"MON k=", tr))
    check("[9] $monitor printed once per CHANGE of its argument (k: 0 -> 1)",
          n_mon == 2, f"{n_mon} line(s) over the whole transient")
    rows = re.search(r"No. of Data Rows\s*:\s*(\d+)", tr)
    n_str = len(re.findall(r"STROBE v=", tr))
    check("[10] un-gated $strobe printed once per accepted point in the transient",
          rows is not None and abs(n_str - int(rows.group(1))) <= 2,
          f"{n_str} strobes vs {rows.group(1) if rows else '?'} accepted rows")

    # 9.4.3: %r engineering notation
    check("[11] %r: 1e3 -> 1.000000k", "r1=[1.000000k]" in op)
    check("[12] %r: 1e-9 -> 1.000000n", "r2=[1.000000n]" in op)
    check("[13] %r: 0.036 -> 36.000000m", "r3=[36.000000m]" in op)
    check("[14] %r: 2.2e4 -> 22.000000k", "r4=[22.000000k]" in op)
    # null argument
    check("[15] a null display argument is a single space (9.4.1)",
          re.search(r"NULLARG: end", op) is not None)

# ---- 9.5.1.1 + lifecycle ----------------------------------------------------
print("\nlrmsysio_files.va (append across analyses, seek, pre-opened streams):")
rc, out, osdi = compile_file("lrmsysio_files.va")
check("[16] compiles", rc == 0, out.strip().splitlines()[-1] if rc else "")
if rc == 0:
    rmfiles("lrmsysio_runs.txt", "lrmsysio_seek.txt")
    body = "N1 a 0 mm\nR1 a 0 1k\n.model mm lrmsysio_files()"
    out2 = run(body, "op\nop", "files", osdi)
    runs = open(os.path.join(HERE, "lrmsysio_runs.txt")).read().split() \
        if os.path.exists(os.path.join(HERE, "lrmsysio_runs.txt")) else []
    check("[17] two analyses in one process -> two RUN lines (9.5.1.1 append)",
          runs == ["RUN", "RUN"], f"{runs}")
    seek = open(os.path.join(HERE, "lrmsysio_seek.txt")).read() \
        if os.path.exists(os.path.join(HERE, "lrmsysio_seek.txt")) else ""
    check("[18] $rewind/$fseek overwrite file is EXACT despite the init re-run",
          seek == "XY234**789", repr(seek))
    check("[19] the pre-opened descriptor 32'h8000_0001 reached stdout",
          "TO_STDOUT_FD" in out2)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
