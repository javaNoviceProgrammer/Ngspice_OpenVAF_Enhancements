#!/usr/bin/env python3
"""Enhancement-481: `.option silentports` -- opt out of the absent-terminal warning.

Enhancement-402 made an omitted OSDI terminal audible, and that stays the
DEFAULT: an omitted terminal looks exactly like a typo, and it DANGLES rather
than grounding, so the natural assumption is the wrong one.

But a schematic front end emits what it emits. KiCad's exporter writes the short
form for every instance of a model that declares an optional thermal port, and
the author cannot change that from the schematic -- so the deck collects five
lines of warning per device about a choice nobody made. `.option silentports`
turns those off, and nothing else.

WHAT IT DOES NOT DO, pinned by [7]-[9]: it silences one WARNING. It does not make
an ill-posed circuit well posed. A model that gates its thermal branch on
`$port_connected` and leaves the node floating still fails the operating point on
a singular matrix -- Enhancement-402's decided territory, where the answer is to
write `0` for the pin. Measured on the BSIM-BULK reproducer: silencing removes
five lines and leaves six `singular matrix: check node n1#t`.

The two shapes, both compiled here:
  * sp_rth.va   -- thermal network contributed unconditionally: well posed with
                   `t` absent, so silencing gives a completely clean run;
  * sp_gated.va -- branch gated on `$port_connected`: the node floats, and the
                   singular matrix is unchanged by the option.

Every OFF spelling is tested. `cp_getvar(.., CP_BOOL, ..)` reports a variable
that is merely PRESENT as true, so `silentports=0`, `=false`, `=no` and `=off`
would each have turned the feature ON -- the defect Enhancements 450, 451, 454,
466 and 467 each shipped exactly once.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_va(stem):
    src = os.path.join(HERE, stem + ".va")
    osdi = os.path.join(HERE, "_" + stem + ".osdi")
    r = subprocess.run([OPENVAF, src, "-o", osdi], capture_output=True, text=True,
                       timeout=300, cwd=HERE, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr), osdi


def run(deck, ctl, tag, osdi, timeout=120):
    path = os.path.join(HERE, f"_sp_{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* silentports {tag}\n{deck}\n.control\npre_osdi {osdi}\n"
                f"option noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=timeout, cwd=HERE, stdin=subprocess.DEVNULL)
    try:
        os.remove(path)
    except OSError:
        pass
    return r.returncode, (r.stdout + r.stderr)


def warn_lines(out):
    """Lines of the Enhancement-402 absent-terminal warning."""
    return len(re.findall(r"are not connected|is absent|port_connected\(\) = 0"
                          r"|NOT grounded -- connect|Line: n1", out))


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


print("Enhancement-481: `.option silentports`\n")

# ------------------------------------------------------------- compile both --
rc, out, OSDI_RTH = compile_va("sp_rth")
check("[1] the well-posed optional-thermal model compiles", rc == 0,
      out.splitlines()[0][:60] if rc else "")
rc, out, OSDI_GATED = compile_va("sp_gated")
check("[1] ...and the $port_connected-gated one", rc == 0,
      out.splitlines()[0][:60] if rc else "")

OMIT = "V1 a 0 dc 1\nN1 a 0 mm\n.model mm sp_rth()"
CONN = "V1 a 0 dc 1\nN1 a 0 0 mm\n.model mm sp_rth()"

# ------------------------------------------- the default is UNCHANGED (E-402) --
print("\nthe default still warns -- Enhancement-402 is not undone")
rc, o = run(OMIT, "op\nprint i(v1)", "default", OSDI_RTH)
check("[2] an omitted terminal warns by default", warn_lines(o) == 5, f"{warn_lines(o)} lines")
check("[2] ...and the deck still simulates", val(o, "i(v1)") is not None
      and abs(val(o, "i(v1)") + 1e-3) < 1e-9, f"i(v1)={val(o,'i(v1)')}")
rc, o = run(CONN, "op\nprint i(v1)", "conn", OSDI_RTH)
check("[3] a fully connected instance never warned and still does not",
      warn_lines(o) == 0, f"{warn_lines(o)} lines")

# ------------------------------------------------------------- the option ----
print("\n.option silentports turns that one warning off")
rc, o = run(".option silentports\n" + OMIT, "op\nprint i(v1)", "silent", OSDI_RTH)
check("[4] the warning is gone", warn_lines(o) == 0, f"{warn_lines(o)} lines")
check("[4] ...the answer is unchanged", val(o, "i(v1)") is not None
      and abs(val(o, "i(v1)") + 1e-3) < 1e-9, f"i(v1)={val(o,'i(v1)')}")
check("[4] ...and it is not reported as an unknown option",
      "unknown option" not in o.lower(), "registered in both places")

print("\nevery ON spelling silences, every OFF spelling does not")
for spelling, want_silent in [("silentports", True), ("silentports=1", True),
                              ("silentports=true", True), ("silentports=yes", True),
                              ("silentports=on", True), ("silentports=0", False),
                              ("silentports=false", False), ("silentports=no", False),
                              ("silentports=off", False)]:
    rc, o = run(f".option {spelling}\n" + OMIT, "op\nprint i(v1)",
                re.sub(r"\W", "", spelling), OSDI_RTH)
    n = warn_lines(o)
    ok = (n == 0) if want_silent else (n == 5)
    check(f"[5] .option {spelling} -> {'silent' if want_silent else 'still warns'}",
          ok and "unknown option" not in o.lower(), f"{n} lines")

# ------------------------------------------------------- a global default ----
print("\na front end can set it globally, without editing netlists")
spiceinit = os.path.join(HERE, ".spiceinit")
with open(spiceinit, "w") as f:
    f.write("set silentports\n")
try:
    rc, o = run(OMIT, "op\nprint i(v1)", "spiceinit", OSDI_RTH)
    check("[6] `set silentports` in .spiceinit silences it too", warn_lines(o) == 0,
          f"{warn_lines(o)} lines")
finally:
    os.remove(spiceinit)
rc, o = run(OMIT, "op\nprint i(v1)", "after", OSDI_RTH)
check("[6] ...and removing it brings the warning back", warn_lines(o) == 5,
      f"{warn_lines(o)} lines")

# ------------------------------------- what the option deliberately does NOT do --
print("\nit silences a warning -- it does not repair the circuit (E-402 stands)")
GOMIT = "V1 a 0 dc 1\nN1 a 0 mm\n.model mm sp_gated()"
rc, o = run(GOMIT, "op\nprint i(v1)", "gated", OSDI_GATED)
sing_default = len(re.findall(r"singular matrix", o, re.I))
check("[7] the gated model's floating node is singular by default", sing_default > 0,
      f"{sing_default} singular lines")
rc, o2 = run(".option silentports\n" + GOMIT, "op\nprint i(v1)", "gated_silent", OSDI_GATED)
check("[8] the warning is silenced there too", warn_lines(o2) == 0, f"{warn_lines(o2)} lines")
check("[8] ...but the singular matrix is UNCHANGED -- write 0 for the pin",
      len(re.findall(r"singular matrix", o2, re.I)) == sing_default,
      f"{len(re.findall(r'singular matrix', o2, re.I))} vs {sing_default}")
GCONN = "V1 a 0 dc 1\nN1 a 0 0 mm\n.model mm sp_gated()"
rc, o = run(GCONN, "op\nprint i(v1)", "gated_conn", OSDI_GATED)
check("[9] ...and writing 0 for the pin is what fixes it",
      len(re.findall(r"singular matrix", o, re.I)) == 0 and val(o, "i(v1)") is not None,
      f"i(v1)={val(o,'i(v1)')}")

# ------------------------------------------------- the option does not overreach --
print("\nit affects that warning and nothing else")
rc, o = run(".option silentports\nV1 a 0 dc 1\nN1 a 0 0 0 mm\n.model mm sp_rth()",
            "op\nprint i(v1)", "toomany", OSDI_RTH)
check("[10] too MANY nodes is still an error", re.search(r"too many nodes", o, re.I) is not None,
      "")

for stem in ("_sp_rth.osdi", "_sp_gated.osdi"):
    p = os.path.join(HERE, stem)
    if os.path.exists(p):
        os.remove(p)

print(f"\n=== {passed}/{checks} checks passed ===")
sys.exit(0 if passed == checks else 1)
