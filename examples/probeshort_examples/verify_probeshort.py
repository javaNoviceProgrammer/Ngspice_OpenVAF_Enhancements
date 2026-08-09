#!/usr/bin/env python3
"""verify_probeshort.py -- Enhancement-406: a flow probe that silently shorts the
branch it was meant to measure.

A declared `branch (a,b) br` and the node pair `(a,b)` are DIFFERENT branches --
which is correct, and what the DAE, the E-400 contribution map and the LRM
compliance notes all agree on. The trap is what follows: probing the flow of a
branch nothing contributes to makes it an ideal ammeter (a 0 V source, E-36), so
contributing through one spelling and probing through the other drops an ammeter
in parallel with the real branch and SHORTS it.

The consequence is numeric and silent. Two 1 kOhm sections in series draw 0.5 mA;
with the first shorted they draw 1.0 mA, rc=0, no diagnostic before this release.

Passes iff:
  * the trap is REPORTED (L023) and still measurably shorted -- the lint reports,
    it does not change the semantics, because the ammeter is a documented feature
    and a model may legitimately want it;
  * the correctly spelled model is SILENT and draws the right current;
  * the deliberate sense-ammeter idiom (nothing else drives the pair) is SILENT --
    this is the false positive to avoid, and six branches in the shipped corpus
    rely on it.

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


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


OSDI = os.path.join(tempfile.gettempdir(), "probeshort.osdi")


def compile_models():
    src = os.path.join(HERE, "probe_short.va")
    r = subprocess.run([OPENVAF, src, "-o", OSDI], capture_output=True, text=True, timeout=600)
    return r.returncode == 0 and os.path.exists(OSDI), r.stdout + r.stderr


def terminal_current(model):
    """i(v1) for a 1 V source driving the device; two 1k in series => -5e-4."""
    path = os.path.join(tempfile.gettempdir(), f"ps_{model}.cir")
    with open(path, "w") as fh:
        fh.write(f"""* probeshort {model}
v1 a 0 dc 1
nd1 a 0 m{model}
.model m{model} {model}()
.control
pre_osdi {OSDI}
op
print i(v1)
.endc
.end
""")
    out = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                         timeout=120).stdout
    m = re.findall(r"i\(v1\)\s*=\s*(-?[\d.eE+-]+)", out)
    return float(m[0]) if m else None


def main():
    print("Enhancement-406: a probe-only branch shorting the branch that is driven\n")
    ok, log = compile_models()
    if not check("probe_short.va compiles", ok):
        print(f"\n{passed}/{checks} checks passed")
        return 1

    fired = [l for l in log.splitlines() if "L023" in l]
    check("the trap is REPORTED (L023)", len(fired) == 1,
          fired[0].strip()[:78] if fired else "no L023 diagnostic")
    check("the report names the probed branch `br`",
          any("`br`" in l for l in fired))
    check("`ok` is not reported", not any("module `ok`" in l for l in fired))
    check("`sense_ok` (deliberate ammeter) is not reported",
          not any("sense_ok" in l for l in fired))
    check("exactly one warning in the whole file", len(fired) == 1, f"{len(fired)} found")

    # the numeric consequence the lint exists to explain
    i_ok = terminal_current("ok")
    i_trap = terminal_current("trap")
    check("correctly spelled model draws 0.5 mA", i_ok is not None and abs(i_ok + 5e-4) < 1e-9,
          f"i(v1)={i_ok}")
    check("trap still draws 1.0 mA -- the lint reports, it does not change semantics",
          i_trap is not None and abs(i_trap + 1e-3) < 1e-9, f"i(v1)={i_trap}")
    if i_ok and i_trap:
        check("the short doubles the current", abs(abs(i_trap / i_ok) - 2.0) < 1e-6,
              f"ratio {i_trap / i_ok:.6f}")

    # suppression, so a model that means it can say so
    src = os.path.join(HERE, "probe_short.va")
    r = subprocess.run([OPENVAF, "--allow", "probe_only_branch_short", src, "-o", OSDI],
                       capture_output=True, text=True, timeout=600)
    check("--allow probe_only_branch_short silences it",
          r.returncode == 0 and "L023" not in (r.stdout + r.stderr))
    r = subprocess.run([OPENVAF, "--deny", "probe_only_branch_short", src, "-o", OSDI],
                       capture_output=True, text=True, timeout=600)
    check("--deny turns it into an error", r.returncode != 0, f"rc={r.returncode}")

    check_controlled_sources()

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


CS_OSDI = os.path.join(tempfile.gettempdir(), "controlled_sources.osdi")

# (module, ports on the instance line, expected v(out), expected lint)
#
# Stimulus: the sense port is driven at exactly 1 mA (1 V through 1 k) and the
# output works into 1 k.  CCVS rm=100 => V(p,n) = 0.1 V.  CCCS beta=100 => 100 mA
# into 1 k.  VCVS gain=10 and VCCS gm=1e-3 see 1 V on their (high-impedance)
# control port.
CONTROLLED = [
    ("va_vcvs",        "out 0 ps 0",  10.0,   None),
    ("va_vccs",        "out 0 ps 0",  -1.0,   None),
    ("ccvs_shorted",   "out 0 ps 0",   0.1,   None),
    ("ccvs_bare",      "out 0 ps 0",   0.1,   "L017"),
    ("ccvs_pair",      "out 0 ps 0",   0.1,   None),
    ("cccs_shorted",   "out 0 ps 0", -100.0,  None),
    ("cccs_bare",      "out 0 ps 0", -100.0,  "L017"),
    ("cccs_pair",      "out 0 ps 0", -100.0,  None),
    ("cccs_port",      "out 0 ps",     None,  None),
    ("cccs_portbranch", "out 0 ps",    None,  None),
    ("cccs_mixed",     "out 0 ps 0",   None,  "L023"),   # broken: the solve fails
]


def cs_out(model, nodes):
    path = os.path.join(tempfile.gettempdir(), f"cs_{model}.cir")
    with open(path, "w") as fh:
        fh.write(f"""* controlled source {model}
v1 vs 0 dc 1
r1 vs ps 1k
rout out 0 1k
nd1 {nodes} m{model}
.model m{model} {model}()
.control
pre_osdi {CS_OSDI}
op
print v(out)
.endc
.end
""")
    out = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                         timeout=120).stdout
    m = re.findall(r"v\(out\)\s*=\s*(-?[\d.eE+-]+)", out)
    return float(m[0]) if m else None


def check_controlled_sources():
    """Enhancement-406: the four controlled sources are where a false positive
    would hurt most -- CCVS and CCCS MUST probe a branch current. Every ordinary
    spelling of all four has to stay silent under L023, and keep working."""
    print("\ncontrolled sources (VCVS / VCCS / CCVS / CCCS)")
    src = os.path.join(HERE, "controlled_sources.va")
    r = subprocess.run([OPENVAF, src, "-o", CS_OSDI], capture_output=True, text=True,
                       timeout=600)
    log = r.stdout + r.stderr
    if not check("controlled_sources.va compiles", r.returncode == 0 and os.path.exists(CS_OSDI)):
        return

    # L023 must name exactly one module, and it must be the broken one
    l023 = [l for l in log.splitlines() if "L023" in l]
    check("L023 fires exactly once across all four families", len(l023) == 1,
          f"{len(l023)} firings")
    check("...and only on the deliberately broken cccs_mixed",
          len(l023) == 1 and "cccs_mixed" in l023[0])
    for m, _, _, want in CONTROLLED:
        if want != "L023":
            check(f"L023 silent on {m}", not any(f"`{m}`" in l for l in l023))

    for model, nodes, want_v, want_lint in CONTROLLED:
        got = cs_out(model, nodes)
        if want_v is None:
            # cccs_mixed cannot solve; the port forms need no numeric pin here
            if model == "cccs_mixed":
                check("cccs_mixed does not solve -- the lint reports a real failure",
                      got is None, f"v(out)={got}")
            continue
        check(f"{model} works: v(out) = {want_v}",
              got is not None and abs(got - want_v) <= 1e-6 * max(1.0, abs(want_v)),
              f"got {got}")

    # `va_` prefixes, because ngspice registers built-in vcvs/vccs/ccvs/cccs devices.
    # openvaf's reserved_module_name lint (L018) catches the collision and its help
    # text predicts the exact failure -- "may silently bind to ngspice's built-in
    # device instead of this OSDI module". Naming them plainly made ngspice refuse
    # the OSDI registration and the instance line fail with "incorrect model type!".
    check("no reserved-name collisions (L018) in this file", "L018" not in log,
          [l for l in log.splitlines() if "L018" in l][:1])

    # the bare sense-branch forms work AND draw the advisory L017 -- the message
    # Enhancement-406 corrected, because the old text called such a probe dead
    l017 = [l for l in log.splitlines() if "L017" in l]
    check("the two bare sense-branch forms draw L017", len(l017) == 2, f"{len(l017)} firings")
    check("L017 no longer claims the probe returns zero",
          all("returns zero" not in l for l in l017))
    check("L017 says the probe shorts the branch",
          all("shorts it" in l for l in l017))

    check_probe_diagnostic()



def check_probe_diagnostic():
    """Enhancement-430: what `.probe` says when it refuses a token.

    `.probe` and `.save` are deliberately different mechanisms, not two
    spellings of one thing. Per the manual (11.7.1) `.probe` MEASURES a current
    by placing a voltage source in series with the device's node -- which is why
    its results come out as `<inst>#branch` -- while `@device[param]` is read out
    of the device, needs no extra node, and is a `.save` item (11.7.3 describes
    `.options savecurrents` as generating `.save @r1[i]` lines).

    So the refusal is correct and stays. What was wrong was the message: it named
    neither the accepted forms nor the right tool, printed TWICE for one bad
    token, and misspelled "ignored" as "ingnored".
    """
    print("\nEnhancement-430: the .probe refusal names the accepted forms and the right tool")

    def run_probe(card):
        path = os.path.join(HERE, "_probe_msg.cir")
        with open(path, "w") as fh:
            fh.write(f"""* probe message
v1 a 0 dc 1
r1 a b 1k
r2 b 0 3k
{card}
.tran 1u 5u
.control
run
.endc
.end
""")
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=120)
        os.remove(path)
        return (r.stdout or "") + (r.stderr or "")

    out = run_probe(".probe @r1[i]")
    check("an @device[param] token is refused exactly ONCE",
          out.count("Warning: .probe accepts") == 1,
          f"{out.count('Warning: .probe accepts')} warnings")
    check("...the message names what .probe does accept",
          "v(...), i(...), p(...) or alli" in out)
    check("...and points at the tool that handles it",
          ".save @r1[i]" in out and "savecurrents" in out,
          out[-200:].replace("\n", " "))
    check("...echoing the card as the user wrote it, not as '*probe'",
          '".probe @r1[i]"' in out and '"*probe' not in out)
    check('the misspelling "ingnored" is gone', "ingnored" not in out)

    out = run_probe(".probe nonsense")
    check("a non-@ bad token is refused once, without the .save hint",
          out.count("Warning: .probe accepts") == 1
          and "belongs to .save" not in out)

    # the forms .probe is FOR must stay silent and keep working
    for card, vec in ((".probe i(r1)", "r1#branch"),
                      (".probe alli", "r1#branch"),
                      (".probe v(b)", None)):
        out = run_probe(card)
        check(f"`{card}` draws no warning", "Warning: .probe accepts" not in out)
        if vec:
            check(f"`{card}` still produces {vec}", vec in out,
                  out[-160:].replace("\n", " "))

if __name__ == "__main__":
    sys.exit(main())
