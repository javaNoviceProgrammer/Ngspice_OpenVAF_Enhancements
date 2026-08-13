#!/usr/bin/env python3
"""Enhancement-450: `savecurrents` could be requested but never declined.

Whether `.options savecurrents` was in force was decided by a bare substring
search over the option line:

    if (strstr(options->line, "savecurrents"))

so EVERY option line merely CONTAINING the word switched it on, whatever the
line actually said. The two spellings a user reaches for to turn it OFF both
turned it ON instead -- `.options savecurrents=0` and `.options nosavecurrents`,
the latter being ngspice's own no<option> convention (noacct, noinit, nomod,
nopage). Once on there was no way back.

Silent in every case, because a deck that quietly saves every terminal current
still simulates correctly; it just carries vectors the user asked not to have,
which on a large deck is the difference between a small rawfile and a huge one.

The option line is now read as TOKENS: exactly `savecurrents`, or one of the
declared `savecurrents_<variant>` names, so an unrelated identifier that merely
contains the word no longer matches; a `no` prefix or a false-looking value
turns it off; the later card wins.

The oracle is the vector list: with the option on, a two-terminal OSDI device
contributes `@n1[i]`, `@n1[i_p]` and `@n1[i_n]` -- one per terminal plus the
two-terminal convenience name (Enhancement-394) -- and with it off, none exist.

Enhancement-413's `savecur_examples` covers what savecurrents PRODUCES once it
is on; this directory covers whether it is on at all.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_sco_"):
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


CORE = "V1 a 0 dc 1\nN1 a 0 scoff\n.model scoff savecuroff r=1k\n"
CTL = (".control\noption noacct\nset numdgt=8\npre_osdi savecuroff.osdi\n"
       "op\ndisplay\nprint v(a)\n.endc\n.end\n")


def run(opt, tag, body=None, ctl=None, timeout=120):
    deck = f"savecuroff {tag}\n{body or CORE}{opt}\n{ctl or CTL}"
    p = os.path.join(HERE, f"_sco_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    return r.returncode, r.stdout + r.stderr


def ncur(out):
    """how many @dev[i...] current vectors the run produced"""
    return len([l for l in out.splitlines() if re.search(r"@\w+\[i", l)])


print("Enhancement-450: savecurrents could be requested but never declined\n")

r = subprocess.run([OPENVAF, "savecuroff.va", "-o", "savecuroff.osdi"], cwd=HERE,
                   capture_output=True, text=True)
check("[E-450] the model compiles", r.returncode == 0 and
      os.path.isfile(os.path.join(HERE, "savecuroff.osdi")), r.stderr.strip()[:60])

# ------------------------------------------------------------ still works ---
print("\nasking for it still works (controls)")
for lbl, opt in ((".options savecurrents", ".options savecurrents"),
                 (".option savecurrents (singular)", ".option savecurrents"),
                 ("savecurrents=1", ".options savecurrents=1"),
                 ("beside other options on one line", ".options reltol=1e-3 savecurrents"),
                 ("a declared variant, savecurrents_mos1", ".options savecurrents_mos1")):
    rc, out = run(opt, re.sub(r"\W", "", lbl)[:16])
    check(f"[E-450] {lbl} still switches it ON", rc == 0 and ncur(out) == 3,
          f"{ncur(out)} current vectors")

rc, out = run("", "off")
check("[E-450] ...and with no option at all there are none (control)",
      rc == 0 and ncur(out) == 0, f"{ncur(out)}")
rc, out = run(".options reltol=1e-3", "unrel")
check("[E-450] ...nor with an unrelated option (control)",
      rc == 0 and ncur(out) == 0, f"{ncur(out)}")

# ------------------------------------------------------- declining it now ---
print("\ndeclining it now works -- each of these used to switch it ON")
for lbl, opt in (("savecurrents=0", ".options savecurrents=0"),
                 ("savecurrents=false", ".options savecurrents=false"),
                 ("savecurrents=no", ".options savecurrents=no"),
                 ("savecurrents=off", ".options savecurrents=off"),
                 ("nosavecurrents", ".options nosavecurrents")):
    rc, out = run(opt, re.sub(r"\W", "", lbl)[:16])
    check(f"[E-450] `.options {lbl}` leaves it OFF", rc == 0 and ncur(out) == 0,
          f"{ncur(out)} current vectors")

rc, out = run(".options mysavecurrentsxyz", "contain")
check("[E-450] an identifier merely CONTAINING the word does not match",
      rc == 0 and ncur(out) == 0, f"{ncur(out)}")

# ------------------------------------------------------------- last wins ---
print("\nthe later card wins, as a repeated .options value does")
rc, out = run(".options savecurrents\n.options nosavecurrents", "onoff")
check("[E-450] on then off -> OFF", rc == 0 and ncur(out) == 0, f"{ncur(out)}")
rc, out = run(".options nosavecurrents\n.options savecurrents", "offon")
check("[E-450] off then on -> ON", rc == 0 and ncur(out) == 3, f"{ncur(out)}")

# ------------------------------------------- the MOS variants are untouched ---
# Each variant selects a DIFFERENT current set off the retained card, so the fix
# has to keep returning the same card the old first-match returned.
print("\nthe MOS variants still select their own current sets")
MOS = ("V1 d 0 dc 1\nVg g 0 dc 2\nM1 d g 0 0 nch w=1u l=1u\n"
       ".model nch nmos level=1 vto=0.5\n")
MCTL = ".control\noption noacct\nop\ndisplay\n.endc\n.end\n"
sets = {}
for v in ("savecurrents", "savecurrents_mos1", "savecurrents_bsim3",
          "savecurrents_bsim4"):
    rc, out = run(f".options {v}", "m" + v[-5:], body=MOS, ctl=MCTL)
    sets[v] = sorted(set(re.findall(r"@m1\[(\w+)\]", out)))
check("[E-450] plain savecurrents on a MOS gives id/ig/is/ib",
      sets["savecurrents"] == ["ib", "id", "ig", "is"], f"{sets['savecurrents']}")
check("[E-450] the four variants remain DISTINCT",
      len({tuple(v) for v in sets.values()}) == 4,
      f"{[len(v) for v in sets.values()]}")
check("[E-450] bsim4 is the widest set", len(sets["savecurrents_bsim4"]) > 6,
      f"{len(sets['savecurrents_bsim4'])} params")

# ------------------------------------------------------- reachable at all ---
print("\nthe currents themselves are still correct")
rc, out = run(".options savecurrents", "vals",
              ctl=(".control\noption noacct\nset numdgt=8\npre_osdi savecuroff.osdi\n"
                   "op\nprint @n1[i_p] @n1[i_n]\n.endc\n.end\n"))
ip = re.search(r"@n1\[i_p\]\s*=\s*(-?[\d.]+e[-+]\d+)", out)
inn = re.search(r"@n1\[i_n\]\s*=\s*(-?[\d.]+e[-+]\d+)", out)
ok = ip and inn and abs(float(ip.group(1)) + float(inn.group(1))) < 1e-12
check("[E-450] the two terminal currents still sum to zero", bool(ok),
      f"{ip.group(1) if ip else '-'} / {inn.group(1) if inn else '-'}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
