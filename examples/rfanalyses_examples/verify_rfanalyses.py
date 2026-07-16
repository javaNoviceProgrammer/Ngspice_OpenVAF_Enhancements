#!/usr/bin/env python3
"""
verify_rfanalyses.py -- verifies Enhancement-63: S-parameter analysis,
transient noise, and periodic steady state (PSS) with Verilog-A (OSDI)
devices, end-to-end through the committed openvaf-r + ngspice.

Round 2 of the Enhancement-62 analysis-coverage probe:

  * `.sp` (S-parameters): OSDI devices are EXACT -- a series 100-ohm OSDI
    resistor between 50-ohm ports gives the textbook S11 = S21 = 0.5, and
    a frequency-dependent OSDI RC shunt is BIT-IDENTICAL to the built-in
    R/C twin across three decades. The analysis is fully N-PORT (span.c
    allocates every matrix CKTportCount x CKTportCount): a 3-port direct
    junction reproduces the textbook Sii = -1/3 / Sij = +2/3, and 3- and
    4-port OSDI resistor stars give the analytic 1/3 and 1/4 exactly.
    Only the donoise noise-parameter block (NF/SOpt/Rn -- inherently
    two-port concepts) is restricted to exactly 2 ports.
  * `.sp ... 1` (donoise): the OSDI noise pipeline reaches S-parameter
    noise figures -- NF = 10*log10(1 + R/Z0) = 4.7712 dB exactly for the
    series noisy resistor. THE FIX: the same topology with a BUILT-IN
    resistor returned NaN -- span.c's noise-parameter extraction takes
    sqrt(Ycor.re^2 + Gu/Rn) where Gu (the uncorrelated noise conductance)
    is analytically ZERO for a fully-correlated single-source topology,
    and floating-point rounding could land the argument at -1e-18. Found
    by OSDI/built-in parity testing; clamped to the physical range >= 0.
    Both now agree with the analytic figure.
  * transient noise (TRNOISE sources): propagates through OSDI devices
    correctly (device-INTERNAL noise does not enter .tran for built-in
    devices either -- parity, documented).
  * PSS (`.pss`, experimental, needs `--enable-pss` at configure): OSDI
    devices are full citizens -- the linear OSDI RC converges to the
    analytic fundamental 1/sqrt(1+(wRC)^2) and matches the built-in twin
    to 7 digits; a mildly-driven OSDI diode converges in 2 shooting
    iterations (the built-in diode twin actually wanders longer). Strongly
    nonlinear rectifiers are hard for the shooting method with built-ins
    and OSDI alike. These checks SKIP automatically when the ngspice
    binary was built without --enable-pss.

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

passed = failed = skipped = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def skip(name, why):
    global skipped
    skipped += 1
    print(f"  SKIP  {name} ({why})")


def compile_va(src):
    osdi = os.path.splitext(src)[0] + ".osdi"
    out = os.path.join(HERE, osdi)
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run([OPENVAF, src, "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr, os.path.exists(out)


def run_deck(name, deck, ng=None, timeout=300):
    with open(os.path.join(HERE, name), "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([ng or NGSPICE, "-b", name],
                           capture_output=True, text=True, timeout=timeout, cwd=HERE)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return out + "\n[TIMEOUT]"
    return r.stdout + r.stderr


def find_pss_ngspice():
    """PSS is compile-time optional. Prefer a build-pss/ sibling binary,
    else probe the default binary; return None if unsupported. A binary
    WITHOUT PSS rejects the dot command instantly; one WITH PSS starts
    shooting -- so even a probe timeout means "supported"."""
    cand = os.path.join(HERE, "..", "ngspice-46", "build-pss", "src", "ngspice")
    for ng in ([cand] if os.path.exists(cand) else []) + [NGSPICE]:
        log = run_deck("_pssprobe.cir", """* pss probe
V1 a 0 SIN(0 1 1meg)
R1 a b 1k
C1 b 0 1n
.pss 1meg 1u b 1024 10 50 5u
.control
run
.endc
.end
""", ng=ng, timeout=15)
        if "unimplemented dot command" not in log:
            return ng
    return None


out, ok = compile_va("rf_blocks.va")
if not ok:
    check("blocks compile", False, out.splitlines()[0] if out else "")
    raise SystemExit(1)

print("[1] .sp: OSDI S-parameters exact")
log = run_deck("_sp.cir", """* sp osdi series R
.control
pre_osdi rf_blocks.osdi
.endc
V1 in 0 DC 0 AC 1 portnum 1 z0 50
N1 in out mm
.model mm ores r=100
V2 out 0 DC 0 AC 1 portnum 2 z0 50
.sp lin 1 1meg 1meg
.control
run
set numdgt=10
print S_1_1 S_2_1
.endc
.end
""")
s11 = re.search(r"s_1_1 = ([0-9.eE+-]+)", log)
s21 = re.search(r"s_2_1 = ([0-9.eE+-]+)", log)
check("S11 == R/(R+2*Z0) == 0.5 exactly",
      s11 and abs(float(s11.group(1)) - 0.5) < 1e-12)
check("S21 == 2*Z0/(R+2*Z0) == 0.5 exactly",
      s21 and abs(float(s21.group(1)) - 0.5) < 1e-12)

print("[2] .sp: frequency-dependent OSDI == built-in (bit-identical)")
spectra = {}
for tag, body in (("osdi", """.control
pre_osdi rf_blocks.osdi
.endc
V1 in 0 DC 0 AC 1 portnum 1 z0 50
N1 in out mm
.model mm ores r=100
N2 out 0 mmc
.model mmc ocap cap=1n
V2 out 0 DC 0 AC 1 portnum 2 z0 50"""),
                  ("builtin", """V1 in 0 DC 0 AC 1 portnum 1 z0 50
R1 in out 100
C1 out 0 1n
V2 out 0 DC 0 AC 1 portnum 2 z0 50""")):
    log = run_deck("_sprc.cir", f"""* sp rc {tag}
{body}
.sp dec 1 1meg 100meg
.control
run
set numdgt=12
print S_2_1
.endc
.end
""")
    spectra[tag] = re.findall(r"^\d+\s+[0-9.eE+-]+\s+(-?[0-9.eE+-]+),\s+(-?[0-9.eE+-]+)",
                              log, re.M)
check("S21(f) identical over 3 decades",
      len(spectra["osdi"]) == 3 and spectra["osdi"] == spectra["builtin"],
      f"({len(spectra['osdi'])} points)")

print("[2b] .sp: arbitrary port count (N-port S-matrices)")
log = run_deck("_sp3j.cir", """* sp 3-port direct junction
V1 p1 0 DC 0 AC 1 portnum 1 z0 50
V2 p2 0 DC 0 AC 1 portnum 2 z0 50
V3 p3 0 DC 0 AC 1 portnum 3 z0 50
R1 p1 star 1u
R2 p2 star 1u
R3 p3 star 1u
.sp lin 1 1meg 1meg
.control
run
set numdgt=10
print S_1_1 S_2_1 S_3_2 S_3_3
.endc
.end
""")
vals = dict(re.findall(r"(s_\d_\d) = (-?[0-9.eE+-]+)", log))
ok3 = (abs(float(vals.get("s_1_1", "9")) + 1.0/3) < 1e-6
       and abs(float(vals.get("s_2_1", "9")) - 2.0/3) < 1e-6
       and abs(float(vals.get("s_3_2", "9")) - 2.0/3) < 1e-6
       and abs(float(vals.get("s_3_3", "9")) + 1.0/3) < 1e-6)
check("3-port junction: Sii == -1/3, Sij == +2/3 (textbook)", ok3)

star = {}
for tag, arm in (("osdi", """N{k} p{k} star mm
"""), ("builtin", """R{k} p{k} star 50
""")):
    pre = """.control
pre_osdi rf_blocks.osdi
.endc
""" if tag == "osdi" else ""
    model = ".model mm ores r=50\n" if tag == "osdi" else ""
    ports = "".join(f"V{k} p{k} 0 DC 0 AC 1 portnum {k} z0 50\n" for k in (1, 2, 3))
    arms = "".join(arm.format(k=k) for k in (1, 2, 3))
    log = run_deck("_sp3s.cir", f"""* sp 3-port star {tag}
{pre}{ports}{arms}{model}.sp lin 1 1meg 1meg
.control
run
set numdgt=12
print S_1_1 S_2_1 S_3_1
.endc
.end
""")
    star[tag] = re.findall(r"s_\d_\d = (-?[0-9.eE+-]+),\s*(-?[0-9.eE+-]+)", log)
check("3-port OSDI star: S11 == S21 == S31 == 1/3 exactly",
      len(star["osdi"]) == 3
      and all(abs(float(re_) - 1.0/3) < 1e-9 and abs(float(im)) < 1e-12
              for re_, im in star["osdi"]))
check("3-port OSDI star == built-in star (bit-identical)",
      star["osdi"] == star["builtin"])

ports4 = "".join(f"V{k} p{k} 0 DC 0 AC 1 portnum {k} z0 50\n" for k in (1, 2, 3, 4))
arms4 = "".join(f"N{k} p{k} star mm\n" for k in (1, 2, 3, 4))
log = run_deck("_sp4s.cir", f"""* sp 4-port star osdi
.control
pre_osdi rf_blocks.osdi
.endc
{ports4}{arms4}.model mm ores r=50
.sp lin 1 1meg 1meg
.control
run
set numdgt=12
print S_1_1 S_2_1 S_4_1 S_4_4
.endc
.end
""")
vals4 = re.findall(r"s_\d_\d = (-?[0-9.eE+-]+)", log)
check("4-port OSDI star: every S == 1/4 exactly",
      len(vals4) == 4 and all(abs(float(v) - 0.25) < 1e-9 for v in vals4))

print("[3] .sp donoise: OSDI noise exact + THE span.c NaN fix")
nf = {}
for tag, body in (("osdi", """.control
pre_osdi rf_blocks.osdi
.endc
V1 in 0 DC 0 AC 1 portnum 1 z0 50
N1 in out mm
.model mm rnoisy r=100
V2 out 0 DC 0 AC 1 portnum 2 z0 50"""),
                  ("builtin", """V1 in 0 DC 0 AC 1 portnum 1 z0 50
R1 in out 100
V2 out 0 DC 0 AC 1 portnum 2 z0 50""")):
    log = run_deck("_spno.cir", f"""* sp noise {tag}
{body}
.sp lin 1 1meg 1meg 1
.control
run
set numdgt=10
print NF SOpt
.endc
.end
""")
    m = re.search(r"nf = ([0-9.eEnan+-]+)", log)
    nf[tag] = m.group(1) if m else "?"
want_nf = 10.0 * math.log10(1.0 + 100.0 / 50.0)   # 4.7712125...
check("OSDI noisy resistor: NF == 10*log10(1+R/Z0) == 4.7712 dB",
      nf["osdi"] != "?" and "nan" not in nf["osdi"]
      and abs(float(nf["osdi"]) - want_nf) < 1e-4, f"(NF={nf['osdi']})")
check("built-in resistor: NF finite and analytic (was NaN before the fix)",
      nf["builtin"] != "?" and "nan" not in nf["builtin"]
      and abs(float(nf["builtin"]) - want_nf) < 1e-6, f"(NF={nf['builtin']})")
log = run_deck("_spno2.cir", """* sp noise 2R regression
V1 in 0 DC 0 AC 1 portnum 1 z0 50
R1 in out 100
R2 out 0 200
V2 out 0 DC 0 AC 1 portnum 2 z0 50
.sp lin 1 1meg 1meg 1
.control
run
set numdgt=10
print NF
.endc
.end
""")
m = re.search(r"nf = ([0-9.eE+-]+)", log)
check("two-resistor NF unchanged by the clamp (7.2016 dB)",
      m and abs(float(m.group(1)) - 7.201593) < 1e-4)

print("[4] transient noise propagates through OSDI devices")
log = run_deck("_trno.cir", """* trnoise through osdi divider
.control
pre_osdi rf_blocks.osdi
.endc
V1 in 0 DC 1 TRNOISE(1m 1n 0 0)
N1 in out mm
.model mm ores r=1k
Rl out 0 1k
.tran 1n 200n
.control
run
print mean(v(out)) stddev(v(out))
.endc
.end
""")
mm = re.search(r"mean\(v\(out\)\) = ([0-9.eE+-]+)", log)
sd = re.search(r"stddev\(v\(out\)\) = ([0-9.eE+-]+)", log)
check("divider mean == 0.5 (deterministic part exact)",
      mm and abs(float(mm.group(1)) - 0.5) < 2e-3)
check("noise reaches the output (0.1mV < sigma < 1mV for 1mV src / 2)",
      sd and 1e-4 < float(sd.group(1)) < 1e-3,
      f"(sigma={sd.group(1) if sd else '?'})")

print("[5] PSS with OSDI devices (auto-skips without --enable-pss)")
ngpss = find_pss_ngspice()
if ngpss is None:
    skip("PSS checks", "ngspice built without --enable-pss; see README")
else:
    fund = {}
    for tag, body in (("osdi", """.control
pre_osdi rf_blocks.osdi
.endc
V1 a 0 SIN(0 1 1meg)
N1 a b mm
.model mm ores r=1k
N2 b 0 mmc
.model mmc ocap cap=1n"""),
                      ("builtin", """V1 a 0 SIN(0 1 1meg)
R1 a b 1k
C1 b 0 1n""")):
        log = run_deck("_pss.cir", f"""* pss {tag}
{body}
.pss 1meg 1u b 1024 10 50 5u
.control
run
set numdgt=10
print mag(b)
.endc
.end
""", ng=ngpss, timeout=600)
        conv = "Convergence reached" in log
        m = re.search(r"^1\s+[0-9.eE+-]+\s+([0-9.eE+-]+)", log, re.M)
        fund[tag] = (conv, float(m.group(1)) if m else float("nan"))
    w = 2 * math.pi * 1e6
    want = 1.0 / math.sqrt(1.0 + (w * 1e3 * 1e-9) ** 2)
    check("OSDI RC: PSS converges, fundamental == 1/sqrt(1+(wRC)^2)",
          fund["osdi"][0] and abs(fund["osdi"][1] - want) < 1e-4,
          f"(|b1|={fund['osdi'][1]:.7f}, want {want:.7f})")
    check("OSDI fundamental == built-in fundamental (1e-6)",
          fund["builtin"][0] and abs(fund["osdi"][1] - fund["builtin"][1]) < 1e-6)
    log = run_deck("_pssd.cir", """* pss mild osdi diode
.control
pre_osdi rf_blocks.osdi
.endc
N1 a b mm
.model mm odio
V1 a 0 SIN(0.6 0.05 1meg)
Rl b 0 1k
.pss 1meg 1u b 256 6 60 3u
.control
run
print b
.endc
.end
""", ng=ngpss, timeout=600)
    check("nonlinear OSDI diode: PSS shooting converges",
          "Convergence reached" in log)

tail = f"{passed} passed, {failed} failed" + (f", {skipped} skipped" if skipped else "")
print(f"\n{'ALL PASS' if failed == 0 else 'FAILURES'}: {tail}")
raise SystemExit(1 if failed else 0)
