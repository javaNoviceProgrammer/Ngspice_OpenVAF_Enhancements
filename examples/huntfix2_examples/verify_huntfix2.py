#!/usr/bin/env python3
"""The openvaf-r hunt round, pinned.

  * H2 (the headline): a terminal-to-terminal short reached through a CHAIN
    of collapses (`V(a,m)<+0; V(m,b)<+0`, m internal) was silently an OPEN
    circuit -- physically identical to the direct `V(a,b)<+0` spelling that
    E-401 turns into a real 0 V source, but the second merge faced a
    terminal-terminal collapse the node mapping cannot honour and was
    dropped with it the whole equation. The simulator now stamps a synthetic
    ideal 0 V source for every refused merge (terminal-terminal and
    terminal-ground), in every analysis, under both solvers. The same
    rewrite fixed two latent merge bugs: a ground-collapsed group merged
    again used to be quietly UN-grounded, and a redundant hint between
    nodes already in one group corrupted the node count.
  * H3: a parameter DEFAULT that violates the parameter's own constant
    range is no longer silent -- the `param_default_out_of_range` lint
    (L027, warn by default) names it at compile time; the deliberate
    must-give idiom silences it per declaration, and all 26 bundled
    industry models stay at zero hits.
  * H1: the E-400 discarded-contribution report now says in as many words
    when the losing site is NOISE-ONLY (it never decides the branch kind,
    but its noise vanishes with the losing kind).
  * H5 (retraction pinned): noise correlation follows the CALL, not the
    label -- separate same-labelled calls sum as powers, one call's output
    reused sums as amplitudes, exactly as the LRM audit (4.6.4.6) and
    E-528 established. Closed-form spectra guard all three shapes.
  * H4: the documented limexp knee (exp up to ln(1e30), tangent above) is
    measured, so handbook 4.4 cannot drift from the implementation.
"""

import atexit
import math
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
        if junk.startswith("_hx_"):
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


def compile_va(name, tag):
    osdi = os.path.join(HERE, f"_hx_{tag}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout + r.stderr, os.path.basename(osdi)


def run_deck(deck, tag, timeout=300):
    p = os.path.join(HERE, f"_hx_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def num(out, name):
    m = re.search(rf"^{re.escape(name)}\s*=\s*(\S+)", out, re.M)
    try:
        return float(m.group(1).rstrip(","))
    except (AttributeError, ValueError):
        return None


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def relclose(a, b, rel=1e-6):
    return a is not None and abs(a - b) <= rel * max(abs(b), 1e-300)


# ---- compile phase ---------------------------------------------------------
print("compile -- the fixes and their diagnostics:")

rc, out, SHORT = compile_va("hxshort.va", "short")
check("[1] hxshort.va (direct + two chains) compiles zero-warning",
      rc == 0 and "warning" not in out.lower())

rc, out, COLL = compile_va("hxcollapse.va", "coll")
check("[2] hxcollapse.va (ground chain, un-ground shape, triangle) compiles "
      "zero-warning", rc == 0 and "warning" not in out.lower())

rc, out, _ = compile_va("hxrange_bad.va", "rbad")
n27 = len(re.findall(r"warning\[L027\]", out))
check("[3] H3: both illegal defaults earn L027 (exclude hit and from miss), "
      "the in-range one does not",
      rc == 0 and n27 == 2 and "'rex'" in out and "'rng'" in out
      and "'rok'" not in out, f"L027 x{n27}")

rc, out, _ = compile_va("hxrange_ok.va", "rok")
check("[4] H3: the allowed must-give idiom, a localparam-derived default and "
      "an overridable-derived default all stay silent",
      rc == 0 and "warning" not in out.lower())

rc, out, NDROP = compile_va("hxnoisedrop.va", "ndrop")
check("[5] H1: the discarded V-noise earns L022 with the noise-only note",
      rc == 0 and "warning[L022]" in out and "noise-only" in out)

rc, out, CORR = compile_va("hxcorr.va", "corr")
ok_corr = rc == 0 and "warning" not in out.lower()
rc, out, LIM = compile_va("hxlimexp.va", "lim")
check("[6] hxcorr.va and hxlimexp.va compile zero-warning",
      ok_corr and rc == 0 and "warning" not in out.lower())

# ---- H2: chained terminal shorts conduct -----------------------------------
print("H2 -- a chained terminal-terminal short is the same circuit as the "
      "direct one:")

out = run_deck(f"""hx chained shorts
V1 s1 0 1
Rs1 s1 a1 100
N1 a1 0 m1
V2 s2 0 1
Rs2 s2 a2 100
N2 a2 0 m2
V3 s3 0 1
Rs3 s3 a3 100
N3 a3 0 m3
.model m1 hxdirect
.model m2 hxchain
.model m3 hxchain3
.control
pre_osdi {SHORT}
op
print i(v1) i(v2) i(v3) v(a1) v(a2) v(a3)
.endc
.end
""", "short")
check("[7] direct spelling: 10 mA through Rs=100 at 1 V",
      close(num(out, "i(v1)"), -1e-2) and close(num(out, "v(a1)"), 0.0))
check("[8] one-internal chain: identical (was i = 0, v(a) = 1 V -- an open)",
      close(num(out, "i(v2)"), -1e-2) and close(num(out, "v(a2)"), 0.0),
      f"i={num(out, 'i(v2)')}")
check("[9] two-internal chain: identical",
      close(num(out, "i(v3)"), -1e-2) and close(num(out, "v(a3)"), 0.0))

out = run_deck(f"""hx chain analyses
V1 s 0 dc 1 ac 1
Rs s a 100
N1 a 0 mm
.model mm hxchain
.control
pre_osdi {SHORT}
op
print i(v1)
ac lin 1 1k 1k
print abs(i(v1))
tran 1u 4u
print v(a)[3] i(v1)[3]
.endc
.end
""", "chainall")
check("[10] the synthetic source stamps in AC (|i| = 10 mA) and transient",
      close(num(out, "abs(i(v1))"), 1e-2) and close(num(out, "i(v1)[3]"), -1e-2)
      and close(num(out, "v(a)[3]"), 0.0))

out = run_deck(f"""hx chain reset
V1 s 0 1
Rs s a 100
N1 a 0 mm
.model mm hxchain
.control
pre_osdi {SHORT}
op
print i(v1)
reset
op
print i(v1)
.endc
.end
""", "chainreset")
vals = re.findall(r"^i\(v1\)\s*=\s*(\S+)", out, re.M)
check("[11] reset tears the synthetic source down and setup rebuilds it "
      "(both ops at 10 mA)",
      len(vals) == 2 and all(abs(float(v) + 1e-2) < 1e-9 for v in vals))

out = run_deck(f"""hx chain sens
V1 s 0 1
Rs s a 100
N1 a 0 mm
.model mm hxchain
.control
pre_osdi {SHORT}
sens i(v1)
setplot sens1
display
.endc
.end
""", "chainsens")
check("[12] `sens` (the double-setup path) completes and reports the Rs row",
      "[TIMEOUT]" not in out and re.search(r"^\s*rs\s", out, re.M) is not None
      and "abort" not in out.lower())

print("H2 -- the merge shapes the old loop got wrong:")
out = run_deck(f"""hx ground chain
V1 s 0 1
Rs s a 100
N1 a b mm
Rb b 0 50
.model mm hxgchain
.control
pre_osdi {COLL}
op
print i(v1) v(a) v(b)
.endc
.end
""", "gchain")
check("[13] terminal-to-ground chain pins the terminal (v(a) = 0, 10 mA)",
      close(num(out, "i(v1)"), -1e-2) and close(num(out, "v(a)"), 0.0))

out = run_deck(f"""hx unground
V1 a 0 1
N1 a 0 mm
.model mm hxung
.control
pre_osdi {COLL}
op
print i(v1)
.endc
.end
""", "ung")
check("[14] re-merging a ground-collapsed group keeps it grounded "
      "(i = 1 V x 1 mS)", close(num(out, "i(v1)"), -1e-3))

out = run_deck(f"""hx triangle
V1 a 0 1
N1 a 0 mm
.model mm hxtri
.control
pre_osdi {COLL}
op
print i(v1)
.endc
.end
""", "tri")
check("[15] a collapse triangle leaves the mapping intact "
      "(three 500-ohm segments in series)",
      relclose(num(out, "i(v1)"), -1.0 / 1500.0, 1e-5))

# ---- H1 / H5: noise physics ------------------------------------------------
print("H1/H5 -- noise: the drop is real, correlation follows the call:")

K_B, T_NOM, R_EQ = 1.380649e-23, 300.15, 500.0  # 1k source || 1k device


def onoise(tag, osdi, model):
    out = run_deck(f"""hx noise {model}
V1 s 0 dc 0 ac 1
Rs s a 1k
N1 a 0 mm
.model mm {model}
.control
pre_osdi {osdi}
noise v(a) V1 lin 1 1000 1000
setplot noise1
print onoise_spectrum
.endc
.end
""", tag)
    return num(out, "onoise_spectrum")


def expect(extra_pwr):
    return math.sqrt(R_EQ * R_EQ * (4 * K_B * T_NOM / 1e3 + extra_pwr))


check("[16] the dropped V-noise really is dropped: output noise is the "
      "source resistor alone",
      relclose(onoise("ndrop", NDROP, "hxnoisedrop"), expect(0.0)))
check("[17] two separate same-labelled calls sum as POWERS (2S -- the "
      "audited LRM 4.6.4.6 semantics)",
      relclose(onoise("csep", CORR, "hxcorrsep"), expect(2e-16)))
check("[18] one call's output contributed twice sums as AMPLITUDES (4S)",
      relclose(onoise("cshr", CORR, "hxcorrshr"), expect(4e-16)))
check("[19] one call scaled by 2 scales power by 4 (4S)",
      relclose(onoise("cscl", CORR, "hxcorrscl"), expect(4e-16)))

# ---- H4: the limexp knee ---------------------------------------------------
print("H4 -- the documented limexp knee:")
out = run_deck(f"""hx limexp
V1 a 0 1
N1 a 0 mm
.model mm hxlimexp
.control
pre_osdi {LIM}
op
.endc
.end
""", "lim")
m = re.search(r"HXLIM r68=(\S+) l80=(\S+)", out)
r68 = float(m.group(1)) if m else None
l80 = float(m.group(2)) if m else None
knee = math.log(1e30)
check("[20] limexp is exactly exp at x = 68 (below the knee)", r68 == 1.0,
      f"r68={r68}")
check("[21] limexp is the tangent line 1e30*(1 + x - ln 1e30) at x = 80",
      relclose(l80, 1e30 * (1.0 + 80.0 - knee), 1e-12), f"l80={l80}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
