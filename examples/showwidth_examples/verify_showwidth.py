#!/usr/bin/env python3
"""Enhancement-589: `show` and `showmod` print every name and value in full.

The classic table printed its name column with "%*.*s" at a fixed 11 and its
device columns at a fixed 21, width AND precision, so a parameter name longer
than 11 characters, or an instance, model or string value longer than 21, was
cut without notice: `averyveryverylonginstanceparam` listed as `averyveryve`,
a hierarchical child's `a__a__a__a__r` as `a__a__a__a_`. The widths are now
chosen per table from the names it prints, nothing is truncated, and the
number of devices per row follows from the widths so the table still fits
`width` when it can.

Checks:
  [1] showmod: 31- and 12-character model parameter names in full, values on
      the same row, and every name right-aligned to one column
  [2] show: a 30-character instance parameter name in full, the `device` and
      `model` header labels aligned to the same column
  [3] a 35-character instance name printed in full; two of them at width 80
      each get their own table, at width 200 they share one header row
  [4] a 49-character string parameter value printed in full
  [5] short names keep the classic layout byte for byte (11 + 1 + 21)
  [6] width 40, narrower than the name, still prints the full name
  [7] an explicit long parameter name after ':' widens the column; an
      unknown long name prints in full on its '?????????' row with the warning
  [8] `show all` and `showmod all` with model-less devices (vsource) run to
      completion (a NULL parameter table must not be dereferenced)
  [9] the '-' placeholder of an unset vector parameter is aligned with the
      value column
  [10] array parameter elements list under their bracketed names
  [11] a hierarchical child's mangled parameter name in full
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="showwidth_")
LONG_INST = "nverylonginstancenameforshow_abcdef"        # 35 characters
LONG_INST2 = "nverylonginstancenameforshow_second"       # 35 characters
LONG_STR = "a string value that is longer than twenty-one chars"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


r = subprocess.run([VAF, os.path.join(HERE, "showwidth.va"), "-o", os.path.join(WORK, "showwidth.osdi")],
                   capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)

DECK = f"""v1 1 0 dc 1
r1 1 2 1k
r2 2 0 2k
d1 2 0 dm
.model dm d is=1e-14 n=1.05
n1 1 0 mm
n2 1 0 mm averyveryverylonginstanceparam=8k
{LONG_INST} 1 0 mm
{LONG_INST2} 1 0 mm
.model mm showwidth twelve_chars=2k label_string="{LONG_STR}"
"""


def run(ctl, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* showwidth {tag}\n{DECK}\n.control\nset noinit\npre_osdi showwidth.osdi\nop\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout, p.stderr, p.returncode


def rows(out, first_token):
    """Lines whose first token is `first_token`."""
    return [ln for ln in out.splitlines() if ln.split() and ln.split()[0] == first_token]


def name_column_width(out, names):
    """Every listed name is right-aligned into one column of width W (its
    field is W characters, then one blank, then the value). Return W if all
    rows agree, else None."""
    widths = set()
    for nm in names:
        for ln in rows(out, nm):
            widths.add(len(ln) - len(ln.lstrip()) + len(nm))
    return widths.pop() if len(widths) == 1 else None


print("Enhancement-589: show / showmod widths follow the names\n")

# ------------------------------------------------------------- [1] ---
out, err, rc = run("showmod mm", "showmod")
long_m = rows(out, "averyveryverylongmodelparameter")
check("[1] showmod prints the 31-character model parameter name in full with its value",
      len(long_m) == 1 and long_m[0].split() == ["averyveryverylongmodelparameter", "1000"],
      long_m[0] if long_m else out[-300:])
tw = rows(out, "twelve_chars")
check("[1] ... and the 12-character one (11 was the old limit)",
      len(tw) == 1 and tw[0].split() == ["twelve_chars", "2000"], tw[0] if tw else "")
w = name_column_width(out, ["averyveryverylongmodelparameter", "twelve_chars", "label_string", "model", "w[0]"])
check("[1] every name of the table is right-aligned to one column, as wide as the longest name",
      w == len("l1__deep_parameter_name_in_child"), f"width {w}")

# ------------------------------------------------------------- [2] ---
out, err, rc = run("show n1", "show_n1")
li = rows(out, "averyveryverylonginstanceparam")
check("[2] show prints the 30-character instance parameter name in full with its value",
      len(li) == 1 and li[0].split() == ["averyveryverylonginstanceparam", "4000"], li[0] if li else out[-300:])
w = name_column_width(out, ["averyveryverylonginstanceparam", "device", "model", "temp", "m"])
check("[2] the `device` and `model` header labels sit in the same widened column",
      w == len("averyveryverylonginstanceparam"), f"width {w}")

# ------------------------------------------------------------- [3] ---
out, err, rc = run(f"show {LONG_INST} {LONG_INST2}", "show_long80")
dev = rows(out, "device")
check("[3] a 35-character instance name is printed in full",
      any(ln.split() == ["device", LONG_INST] for ln in dev), "; ".join(dev))
check("[3] at width 80 the two long-named instances get one table each (a column is 35 wide)",
      len(dev) == 2 and {tuple(ln.split()) for ln in dev} == {("device", LONG_INST), ("device", LONG_INST2)},
      "; ".join(dev))
out, err, rc = run(f"set width=200\nshow {LONG_INST} {LONG_INST2}", "show_long200")
dev = rows(out, "device")
check("[3] at width 200 they share one header row",
      len(dev) == 1 and dev[0].split()[0] == "device" and set(dev[0].split()[1:]) == {LONG_INST, LONG_INST2},
      "; ".join(dev))
vals = rows(out, "averyveryverylonginstanceparam")
check("[3] ... with both values on one row",
      len(vals) == 1 and vals[0].split() == ["averyveryverylonginstanceparam", "4000", "4000"], "; ".join(vals))

# ------------------------------------------------------------- [4] ---
out, err, rc = run("showmod mm", "showmod_str")
ls = rows(out, "label_string")
check("[4] a 49-character string value is printed in full (21 was the old limit)",
      len(ls) == 1 and ls[0].split(None, 1)[1] == LONG_STR, ls[0] if ls else "")

# ------------------------------------------------------------- [5] ---
out, err, rc = run("show r1", "show_r1")
check("[5] short names keep the classic layout: 11-wide label, 21-wide column",
      "     device                    r1" in out.splitlines()
      and " resistance                  1000" in out.splitlines(),
      "\n".join(ln for ln in out.splitlines() if "device" in ln or "resistance" in ln))
out, err, rc = run("showmod dm", "showmod_dm")
check("[5] ... and for a built-in model table",
      "      model                    dm" in out.splitlines() and "         is                 1e-14" in out.splitlines(),
      "\n".join(ln for ln in out.splitlines() if ln.strip().startswith(("model", "is ")))[:200])

# ------------------------------------------------------------- [6] ---
out, err, rc = run("set width=40\nshow n2", "show_w40")
li = rows(out, "averyveryverylonginstanceparam")
check("[6] a width narrower than the name still prints the whole name (one device per table)",
      len(li) == 1 and li[0].split() == ["averyveryverylonginstanceparam", "8000"], li[0] if li else out[-200:])

# ------------------------------------------------------------- [7] ---
out, err, rc = run("show n2 : averyveryverylonginstanceparam m", "show_explicit")
li = rows(out, "averyveryverylonginstanceparam")
mm = rows(out, "m")
check("[7] an explicit long parameter name after ':' prints in full and widens the column for `m` too",
      len(li) == 1 and li[0].split() == ["averyveryverylonginstanceparam", "8000"]
      and len(mm) == 1 and len(mm[0]) - len(mm[0].lstrip()) + 1 == len("averyveryverylonginstanceparam"),
      (li[0] if li else "") + " | " + (mm[0] if mm else ""))
out, err, rc = run("show n2 : nosuch_parameter_with_a_long_name", "show_unknown")
q = rows(out, "nosuch_parameter_with_a_long_name")
check("[7] an unknown long name prints in full on its '?????????' row, with the E-491 warning",
      len(q) == 1 and q[0].split() == ["nosuch_parameter_with_a_long_name", "?????????"]
      and "has no parameter 'nosuch_parameter_with_a_long_name'" in err, (q[0] if q else "") + " | " + err.strip()[-120:])

# ------------------------------------------------------------- [8] ---
out, err, rc = run("show all\nshowmod all", "show_all")
check("[8] `show all` and `showmod all` with model-less devices present run to completion",
      rc == 0 and "Diode models" in out and rows(out, "is") and rows(out, "averyveryverylongmodelparameter"),
      f"rc={rc}")

# ------------------------------------------------------------- [9] ---
out, err, rc = run("show v1", "show_v1")
dc = rows(out, "dc")
pulse = rows(out, "pulse")
check("[9] the '-' of an unset vector parameter ends in the value column, like a number",
      len(dc) == 1 and len(pulse) == 1 and len(dc[0].rstrip()) == len(pulse[0].rstrip())
      and pulse[0].split() == ["pulse", "-"], (dc[0] if dc else "") + " | " + (pulse[0] if pulse else ""))

# ------------------------------------------------------------ [10] ---
out, err, rc = run("showmod mm", "showmod_arr")
w1 = rows(out, "w[1]")
check("[10] array parameter elements list under their bracketed names",
      len(w1) == 1 and w1[0].split() == ["w[1]", "2"], w1[0] if w1 else "")

# ------------------------------------------------------------ [11] ---
deep = rows(out, "l1__deep_parameter_name_in_child")
check("[11] a hierarchical child's mangled parameter name (32 characters) prints in full",
      len(deep) == 1 and deep[0].split() == ["l1__deep_parameter_name_in_child", "1000"], deep[0] if deep else "")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
