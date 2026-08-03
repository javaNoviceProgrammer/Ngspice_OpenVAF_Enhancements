#!/usr/bin/env python3
"""verify_wildrestore.py -- Enhancement-409: a wildcard sweep knob is put back
when the sweep ends, and stops printing a bogus parser error.

Enhancement-385 gave `sweep` the courtesy of restoring an `alter`/`altermod`
knob, so a following analysis does not silently run against the last swept
point. It reads the nominal with `sw_read_knob()`, which parses the knob name as
an expression -- and a WILDCARD cannot be parsed that way at all: the expression
lexer's `specials` set contains '*', so `@*[p]` never lexes as one token. Two
consequences, both fixed here:

  1. The failed parse PRINTED, and the leftover text made it look like the
     parameter name was broken:

         Error: no such device or model name
         PPerror: syntax error in line segment
            @*[wavelength]
         near
               wavelength]

  2. The read reported failure, and E-385's deliberate ALL-OR-NOTHING rule then
     skipped restoring EVERYTHING -- so a wildcard sweep left every target at
     its last swept value, and with `-vs` it took a concrete co-knob down with
     it.

THE CASE ONE NUMBER CANNOT UNDO, and the reason the fix is per-target: the two
model cards below start at DIFFERENT wavelengths (2 and 9). A wildcard sets both
to one value, so undoing it needs one reading per target, not a single nominal.

WHY THIS SURVIVED E-385's OWN AUDIT: `staterestore_examples/audit/audit_state.py`
sweeps `@r1[resistance]` -- a CONCRETE knob -- and reports `sweep` clean on the
defective binary too. The wildcard forms were never exercised.

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0
OSDI = os.path.join(tempfile.gettempdir(), "wlrestore.osdi")

# dev1 and dev2 deliberately differ, so a single-nominal "restore" cannot pass
NOMINAL = {"dev1[wavelength]": 2.0, "dev2[wavelength]": 9.0,
           "nx1[scale]": 1.0, "nx2[scale]": 1.0}
PROBES = "@dev1[wavelength] @dev2[wavelength] @nx1[scale] @nx2[scale]"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(name, cmd):
    path = os.path.join(tempfile.gettempdir(), f"wr_{name}.cir")
    with open(path, "w") as fh:
        fh.write(f"""* wildrestore {name}
NX1 n1 0 dev1
NX2 n2 0 dev2
v1 n1 0 1
v2 n2 0 1
.model dev1 wlrestore wavelength=2
.model dev2 wlrestore wavelength=9
.control
pre_osdi {OSDI}
op
print {PROBES}
{cmd}
op
print {PROBES}
.endc
.end
""")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def readings(out, name):
    return re.findall(r"@" + re.escape(name) + r"\s*=\s*(-?[\d.eE+-]+)", out)


def unrestored(out):
    """Names whose value differs before vs after, with what they became."""
    bad = []
    for n, want in NOMINAL.items():
        v = readings(out, n)
        if len(v) >= 2 and abs(float(v[0]) - float(v[-1])) > 1e-9:
            bad.append(f"{n} {v[0]}->{v[-1]}")
    return bad


def nominals_intact(out):
    """Every probe must both START at its nominal and END there."""
    for n, want in NOMINAL.items():
        v = readings(out, n)
        if len(v) < 2:
            return False, f"{n}: no reading"
        if abs(float(v[0]) - want) > 1e-9:
            return False, f"{n}: starts at {v[0]}, want {want}"
        if abs(float(v[-1]) - want) > 1e-9:
            return False, f"{n}: ends at {v[-1]}, want {want}"
    return True, ""


SWEEPS = {
    "model wildcard  @*[wavelength]": "sweep @*[wavelength] 1 3 1",
    "inst wildcard   @#*[scale]": "sweep @#*[scale] 1 3 1",
    "E-269 alias     @*[[scale]]": "sweep @*[[scale]] 1 3 1",
    "concrete -vs wildcard": "sweep @dev1[wavelength] 1 3 1 -vs @#*[scale] 5 7 1",
    "wildcard -vs concrete": "sweep @#*[scale] 1 3 1 -vs @dev2[wavelength] 5 7 1",
    "concrete alone (control)": "sweep @dev1[wavelength] 1 3 1",
}
TAIL = " -analysis op -output i1=i(v1)"


def main():
    print("Enhancement-409: a wildcard sweep knob is restored, and stops "
          "printing a parser error\n")
    r = subprocess.run([OPENVAF, os.path.join(HERE, "wlrestore.va"), "-o", OSDI],
                       capture_output=True, text=True, timeout=600)
    if not check("wlrestore.va compiles", r.returncode == 0 and os.path.exists(OSDI),
                 (r.stdout + r.stderr).strip().splitlines()[:1]):
        print(f"\n{passed}/{checks} checks passed")
        return 1

    print("\n  every knob is put back, and nothing is printed that looks like an error")
    for label, cmd in SWEEPS.items():
        out = run(label.split()[0] + str(abs(hash(label)) % 9999), cmd + TAIL)
        ran = re.findall(r"sweep: .*?over (\d+) points", out)
        # the sweep must still DO its job -- a no-op restores trivially
        if not check(f"{label:28s} runs", ran == ["3"] or ran == ["3", "3"],
                     f"points={ran}"):
            continue
        check(f"{label:28s} no parser error", "PPerror" not in out,
              [l.strip() for l in out.splitlines() if "PPerror" in l][:1])
        ok, why = nominals_intact(out)
        check(f"{label:28s} every knob restored", ok, why or str(unrestored(out)))

    print("\n  the sweep still sweeps -- values must change while it runs")
    out = run("values", "sweep @*[wavelength] 1 3 1 -analysis op -output i1=i(v1)\n"
                        "print i1")
    # R = wavelength*scale*1k across a 1 V source, so the source current is
    # -1/(w*1000) -- negative by i(v) sign convention. The swept plot has a
    # single value column beside the index.
    got = re.findall(r"^\s*\d+\s+(-?[\d.eE+-]+)\s*$", out, re.M)
    want = [-1.0 / (w * 1000.0) for w in (1.0, 2.0, 3.0)]
    check("i1 follows -1/(wavelength*1k) at the three points",
          len(got) >= 3 and all(abs(float(g) - w) <= 1e-9 + 1e-6 * abs(w)
                                for g, w in zip(got[:3], want)),
          str(got[:3]))

    print("\n  a wildcard that matches nothing is still reported, and changes nothing")
    out = run("absent", "sweep @*[nosuchparam] 1 3 1 -analysis op -output i1=i(v1)")
    ok, why = nominals_intact(out)
    check("nothing is disturbed", ok, why)
    check("...and it says so", "nosuchparam" in out.lower())

    print("\n  the concrete path E-385 already handled is untouched")
    out = run("conc2", "sweep @dev2[wavelength] 4 6 1 -analysis op -output i1=i(v1)")
    ok, why = nominals_intact(out)
    check("a concrete model knob still restores", ok, why)
    check("...with no parser error", "PPerror" not in out)

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    sys.exit(main())
