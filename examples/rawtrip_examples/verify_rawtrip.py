#!/usr/bin/env python3
"""Enhancement-373: a rawfile round trip lost the scale column and renamed the axis.

FRESH AXIS. [E-226](../../enhancements_doc/Enhancement-226.md) fuzzed rawfile
LOADING with malformed input, looking for crashes. This asks a different and
stronger question: does a rawfile written by ngspice, then loaded by ngspice, still
hold the same data? Round-trip identity is a perfect oracle -- no reference
implementation is needed, and it catches silent fidelity loss that a crash fuzzer
cannot see. It also lands on freshly-changed code, since
[E-371](../../enhancements_doc/Enhancement-371.md) had just touched rawfile.c.

Two independent defects came out of it. NEITHER corrupted a value.

  [1] `print` LOST THE X-AXIS COLUMN for any loaded plot.

          before write:  Index   v-sweep         v(mid)
          after  load:   Index   v(mid)

      `print` prepends the scale column only when `pl_ndims` is non-zero
      (postcoms.c), and outitf.c sets it to 1 for every analysis plot -- but the
      rawfile reader never set it at all, so every loaded plot carried 0 and
      printed its data with no indication of which x-value each row belonged to.
      Proven rather than inferred: a one-line probe setting pl_ndims on load
      restored the column exactly, before the real fix was written.

      Scope, checked rather than assumed: `print` only. `wrdata` was unaffected
      throughout, and the values themselves always round-tripped exactly.

  [2] THE `.dc` SWEEP AXIS WAS RENAMED, `v-sweep` -> `v(v-sweep)`, in the written
      file. The writer wraps a voltage-typed name that has no `v(` prefix, which
      is right for a node probe ("the voltage AT node X") and wrong for a sweep
      AXIS. It did not compound over repeated trips -- the prefix test makes a
      second pass leave `v(v-sweep)` alone -- so the damage was a one-time rename,
      but the name still did not survive.

      Node voltages are already named `v(mid)` internally and take the same
      branch, and `let` vectors are SV_NOTYPE, so the plot's scale was the only
      thing that else-branch was ever reached by.

THE OP ROW IS THE CONTROL THAT MATTERS. Setting pl_ndims=1 on load could have made
`print` invent a scale column for a plot that has no real scale -- an `op` plot's
"variable 0" is just data. It does not: print's inner
`pl_scale && !vec_eq(bv, pl_scale)` test still suppresses it, and `op` prints the
same header before and after. That row is why this fix is safe, so it is checked
explicitly.
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


NET = ("rawtrip\nV1 in 0 dc 0.5 ac 1 sin(0.5 0.2 1meg)\n"
       "Rs in mid 1k\nRl mid out 1k\nC1 mid 0 1n\n")


def run(ctl, tag, timeout=180):
    p = os.path.join(HERE, "_rt_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(NET + ".control\noption noacct\nset numdgt=16\n" + ctl + "\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout, errors="replace")
    return r.stdout + r.stderr


def header(out, marker):
    """The `Index ...` column header of the print block following `marker`."""
    seg = out.split(marker, 1)
    if len(seg) < 2:
        return None
    m = re.search(r"^Index\s+(.*?)\s*$", seg[1], re.M)
    return " ".join(m.group(1).split()) if m else ""


ANALYSES = [
    ("tran", "tran 100n 300n", "time"),
    ("ac", "ac dec 2 1e3 1e4", "frequency"),
    ("dc", "dc V1 0 1 0.5", "v-sweep"),
    ("op", "op", None),          # no scale -- the control
]


def main():
    for ftype in ("ascii", "binary"):
        for name, analysis, scale in ANALYSES:
            out = run("set filetype=%s\n%s\necho BEF\nprint v(mid)\n"
                      "write _t.raw all\nload _t.raw\necho AFT\nprint v(mid)"
                      % (ftype, analysis), "%s_%s" % (ftype, name))
            b, a = header(out, "BEF"), header(out, "AFT")
            # [1] the printed columns must be identical across the round trip
            check("%-6s %s: print columns survive the round trip" % (ftype, name),
                  b is not None and b == a, "before=[%s] after=[%s]" % (b, a))
            # [2] and for the scaled analyses the axis must be there, by name
            if scale:
                check("%-6s %s: axis '%s' present after load" % (ftype, name, scale),
                      a is not None and scale in a, a or "no header")
            else:
                # The control: `op` has no scale. Its `print` uses the scalar form
                # ("v(mid) = 5.0e-01") with NO `Index` header at all, so the
                # correct assertion is that no header appears on either side --
                # pl_ndims=1 must not conjure a column out of variable 0.
                check("%-6s op: no scale column invented (control)" % ftype,
                      b == "" and a == "", "no Index header, before or after")

    # [3] the scale NAME as written to the file -- not wrapped in v(...)
    out = run("set filetype=ascii\ndc V1 0 1 0.5\nwrite _n.raw all\n", "nm")
    p = os.path.join(HERE, "_n.raw")
    names = []
    if os.path.exists(p):
        seg = open(p, errors="replace").read().split("Variables:", 1)
        if len(seg) > 1:
            for line in seg[1].splitlines():
                f = line.split()
                if len(f) >= 2 and re.fullmatch(r"\d+", f[0]):
                    names.append(f[1])
                if line.startswith("Values"):
                    break
    check("written file names the dc axis 'v-sweep', not 'v(v-sweep)'",
          "v-sweep" in names and "v(v-sweep)" not in names,
          " ".join(names) if names else "no Variables block")

    # [4] values must be bit-exact through a binary trip -- read back with
    #     wrdata, which is independent of the print path the fix touched
    for ftype in ("ascii", "binary"):
        outs = []
        for stage in ("before", "after"):
            # distinct filenames per (ftype, stage): reusing one name across the
            # two filetypes let a stale file from the previous iteration be read
            base = "_v_%s_%s" % (ftype, stage)
            tail = ("write _v_%s.raw v(mid)\nload _v_%s.raw\n" % (ftype, ftype)
                    if stage == "after" else "")
            f = os.path.join(HERE, base + ".txt")
            if os.path.exists(f):
                os.remove(f)
            run("set filetype=%s\ntran 20n 400n\n%swrdata %s.txt v(mid)"
                % (ftype, tail, base), base)
            outs.append(open(f, errors="replace").read() if os.path.exists(f) else None)
        if not (outs[0] and outs[1]):
            check("%-6s values survive the trip (via wrdata)" % ftype, False, "missing output")
            continue
        if ftype == "binary":
            # binary stores the raw doubles, so this must be EXACT
            check("binary values bit-identical through the trip (via wrdata)",
                  outs[0] == outs[1], "identical" if outs[0] == outs[1] else "differ")
        else:
            # ASCII is lossy at the last bit and that is OUT OF SCOPE here: the
            # writer emits `%.*e` with prec = DEFPREC, i.e. 16 significant digits,
            # while reproducing a double exactly needs 17. Measured with
            # numdgt=16, 33 of 59 rows differ -- always in the SCALE column and
            # always in the 17th digit (4.0000000000000004e-11 read back as
            # 3.9999999999999998e-11, i.e. 1 ULP); the data values were identical.
            # So compare numerically with a 1e-15 relative tolerance rather than
            # byte-wise, and let the precision question be its own change.
            def nums(t):
                return [float(x) for line in t.splitlines() for x in line.split()]
            A, B = nums(outs[0]), nums(outs[1])
            worst = (max((abs(x - y) / max(abs(x), abs(y), 1e-300)
                          for x, y in zip(A, B)), default=0.0)
                     if len(A) == len(B) else 1.0)
            check("ascii  values survive the trip to 1e-15 (ASCII is 1-ULP lossy)",
                  len(A) == len(B) and worst < 1e-15,
                  "%d values, max rel dev %.2e" % (len(A), worst))

    for j in os.listdir(HERE):
        if j.startswith("_rt_") or j.startswith("_t.") or j.startswith("_n.") \
                or j.startswith("_v"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
