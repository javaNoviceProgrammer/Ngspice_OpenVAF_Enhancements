#!/usr/bin/env python3
"""Enhancement-384: six defects found by hunting around `sens` and the RF ports.

The one that matters is [2]. The rest were found on the way to it, or by asking
what else the same seam got wrong.

  [1] `sens` KILLED THE PROCESS on any deck carrying a `portnum` source.
      vsrcset.c allocates the port's internal "res" node with no `already
      allocated?` guard -- unlike the branch-current node ten lines above, which
      has one. cktsens.c calls each device's DEVsetup a SECOND time to build its
      perturbation matrix, checks that no node was added, and calls
      controlled_exit() when one was. Three components were enough to end the
      session with "please report this issue !".

  [2] `sens` LEFT EVERY LATER TRANSIENT AT EXACTLY ZERO -- silently.

          tran 20n 2u   ->  v(in)[5] = 2.010484e-02
          sens v(out)
          tran 20n 2u   ->  v(in)[5] = 0.000000e+00     <-- driven source node!

      The cause is not in sens at all. VSRCparam's `pwr` and `freq` cases set
      `here->VSRCfunctionType = PORT` UNCONDITIONALLY, and every voltage source
      has those parameters, not just ports. `sens` perturbs every settable real
      parameter of every device, so it wrote `pwr`/`freq` on ordinary sources,
      flipped them to PORT (power 0), and restored the VALUE afterwards but never
      the function type. The deck's SIN was gone for the rest of the session.
      `alter @v1[pwr]=0` did the same damage in one line, with no sens involved.
      Blast radius measured before the fix: tran and envelope zeroed, hb/pss
      failing with |F|=nan while blaming the user's circuit, op/dc ~60x less
      accurate, ac/tf/pz shifted 1e-7..2e-6. Only `reset` cleared it.

  [3] `sp` WITH NO PORTS ENDED THE PROCESS. Forgetting `portnum` is an ordinary
      deck mistake; it called controlled_exit(EXIT_BAD).

  [4] `sp` WITH z0 <= 0 SILENTLY PRODUCED A PARTIAL, WRONG ANSWER. vsrctemp.c
      demoted such a port to "not a port" without a word, so a 2-port with
      `z0=0` on port 2 yielded a plot holding only S_1_1 -- no S_1_2, S_2_1 or
      S_2_2 -- and an S_1_1 of 0.9512 where the correct value is 0.9089.

  [5] OSDI: A MODEL DECLARING `DT` GOT A BOGUS `dtemp` THAT WAS SILENTLY
      IGNORED. osdiregistry.c tested `dt`/`temp` with case-SENSITIVE strcmp in
      one branch and strcasecmp in the next, so `DT` and `dt` were classified
      differently. Exactly the mistake Enhancement-335 fixed one line above for
      `m`, left in place for `dt` and `temp`.

  [6] TWO PARAMETER-TABLE INCONSISTENCIES that ngspice's own `check_ifparm`
      reports and nothing in this repo ever ran. The diode's `tref` aliases
      `tnom` but dropped IF_NONSENSE -- the flag that keeps a parameter out of
      sensitivity analysis -- so two spellings of one parameter disagreed about
      whether they were sensitivity-able. The MESFET's `m` was flagged
      IF_REDUNDANT ("alias of the previous entry") while carrying its own id.
      An independent checker over all 972 device files found these two and no
      others.

WHY [2] SURVIVED A CAMPAIGN AIMED AT IT. This project already has a
cross-analysis sequence fuzzer, and `sens` is in its pool. Its netlist carries
`portnum 1 z0 50`, so every `sens` case it generated died instantly on [1] --
sens was never actually exercised. And its oracle is crash-only ("a clean error
is a PASS, the findings are sanitizer reports, signals, and hangs"), which a
zeroed transient does not trip. Two blind spots stacked.
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


def run(deck, tag, timeout=600):
    p = os.path.join(HERE, "_ss_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "__TIMEOUT__"


def num(out, name):
    m = re.search(r"^%s\s*=\s*([-+0-9.eE]+)" % re.escape(name), out, re.M)
    return float(m.group(1)) if m else None


RC = ("V1 in 0 dc 1 SIN(0 1 1meg)\n"
      "R1 in out 1k\n"
      "R2 out 0 1k\n")
PORT2 = ("V1 in 0 dc 0 ac 1 portnum 1 z0 50\n"
         "V2 out 0 dc 0 ac 0 portnum 2 z0 %s\n"
         "R1 in out 1k\n"
         "R2 out 0 1k\n")
CTL = ".control\noption noacct\nset numdgt=10\n%s\n.endc\n.end\n"


def main():
    # ---- [1] sens no longer kills a deck that has an RF port ---------------
    out = run("f1\nV1 in 0 dc 0.5 portnum 1 z0 50\nR1 in out 1k\nR2 out 0 1k\n"
              + CTL % "sens v(out)\nsetplot\necho SURVIVED", "f1")
    check("sens on a deck with a portnum source does not abort",
          "SURVIVED" in out and "Internal Error" not in out,
          "aborted" if "Internal Error" in out else "ok")
    check("...and it still produces a sensitivity plot",
          "Sensitivity Analysis" in out)

    # ---- [2] the big one: sens must not poison the session ------------------
    ref = run("f2a\n" + RC + CTL % "tran 20n 2u\nprint v(in)[5]", "f2a")
    aft = run("f2b\n" + RC + CTL % "sens v(out)\ntran 20n 2u\nprint v(in)[5]", "f2b")
    a, b = num(ref, "v(in)[5]"), num(aft, "v(in)[5]")
    check("a tran after sens matches the same tran run alone",
          a is not None and b is not None and abs(a - b) <= 1e-9 * max(abs(a), 1e-30),
          "alone=%s after=%s" % (a, b))

    # the same damage without sens: writing `pwr` on an ordinary source
    alt = run("f2c\n" + RC + CTL %
              "tran 20n 2u\nprint v(in)[5]\nalter @v1[pwr]=0\n"
              "tran 20n 2u\nprint v(in)[5]", "f2c")
    vals = re.findall(r"^v\(in\)\[5\]\s*=\s*([-+0-9.eE]+)", alt, re.M)
    check("alter @v1[pwr] does not destroy the source's SIN waveform",
          len(vals) == 2 and abs(float(vals[0]) - float(vals[1])) <= 1e-9 * abs(float(vals[0])),
          " then ".join(vals) if len(vals) == 2 else "%d values" % len(vals))

    # and the analyses that were worst hit
    # `envelope` names its vectors <node>_amp/_dc/_re/_im (com_envelope.c), not
    # a generic "envamp" -- worth stating, because a wrong vector name here reads
    # exactly like the defect: both runs return None and compare equal.
    for an, probe, tag in (("envelope out 1meg 20u", "print out_amp[1]", "env"),
                           ("op", "print v(out)", "op")):
        r1 = run("f2d\n" + RC + CTL % (an + "\n" + probe), tag + "1")
        r2 = run("f2e\n" + RC + CTL % ("sens v(out)\n" + an + "\n" + probe), tag + "2")
        k = probe.split()[1]
        x, y = num(r1, k), num(r2, k)
        check("%s after sens matches %s alone" % (an.split()[0], an.split()[0]),
              x is not None and y is not None
              and abs(x - y) <= 1e-9 * max(abs(x), 1e-30),
              "alone=%s after=%s" % (x, y))

    # ---- [3] sp with no ports reports and returns -------------------------
    out = run("f3\nV1 in 0 dc 0 ac 1\nR1 in out 1k\nR2 out 0 1k\n"
              + CTL % "sp lin 3 1e6 1e8\necho SURVIVED", "f3")
    check("sp with no ports reports an error without ending the session",
          "SURVIVED" in out and "No RF Port is present" in out,
          "session ended" if "SURVIVED" not in out else "ok")

    # ---- [4] sp with a non-positive z0 says so -----------------------------
    out = run("f4\n" + (PORT2 % "0") + CTL % "sp lin 1 1e8 1e8\ndisplay", "f4")
    svec = re.findall(r"^\s*(S_\d_\d)", out, re.M)
    check("sp with z0 = 0 reports it instead of silently dropping the port",
          "reference impedance must be positive" in out,
          "no diagnostic; emitted %s" % (svec or "nothing"))
    check("...and does not emit a partial S-matrix", not svec,
          " ".join(svec) if svec else "none")

    # ---- [5] OSDI: DT and dt must classify identically ---------------------
    osdi = os.path.join(HERE, "_rlowdt.osdi")
    env = dict(os.environ, RAYON_NUM_THREADS="1")
    cp = subprocess.run([OPENVAF, os.path.join(HERE, "rlowdt.va"), "-o", osdi],
                        cwd=HERE, capture_output=True, text=True, env=env, timeout=900)
    if cp.returncode != 0:
        check("rlowdt.va compiles", False, cp.stderr.strip()[:120])
    else:
        check("rlowdt.va compiles", True)
        base = ("f5\n.control\npre_osdi _rlowdt.osdi\n.endc\n"
                "V1 in 0 dc 1\nN1 in out mymod %s\nR2 out 0 1k\n"
                ".model mymod rlowdt %s\n")
        # a model declaring DT must REJECT ngspice's synthesized dtemp, exactly
        # as the same model spelled `dt` always did -- not swallow it silently
        out = run(base % ("dtemp=50", "") + CTL % "op\nprint v(out)", "f5a")
        check("a model declaring DT rejects a bogus instance-line dtemp",
              "unknown parameter" in out.lower(),
              "silently accepted, v(out)=%s" % num(out, "v(out)"))
        # ACCEPT: the model's own parameter still works, and still has an effect
        out = run(base % ("", "DT=50") + CTL % "op\nprint v(out)", "f5b")
        v = num(out, "v(out)")
        check("the model's own DT still applies (r0*(1+0.01*DT) -> 0.4)",
              v is not None and abs(v - 0.4) < 1e-6, "v(out)=%s" % v)

    # ---- [6] ngspice's own table checker is clean --------------------------
    out = run("f6\nV1 in 0 dc 1\nR1 in 0 1k\n" + CTL % "check_ifparm", "f6")
    errs = re.findall(r"ERROR, (?:alias|dataType)[^\n]*", out)
    check("check_ifparm reports no parameter-table inconsistencies",
          not errs, "; ".join(e[:60] for e in errs) if errs else "clean")

    # ======================= ACCEPT HALF ===================================
    # These must hold on BOTH binaries. [2]'s fix touches the parameter that
    # makes a source a PORT, and [4]'s touches port setup, so the RF path is
    # exactly what a careless fix would break.
    out = run("a1\n" + (PORT2 % "50") + CTL %
              "sp lin 1 1e8 1e8\nprint mag(S_1_1) mag(S_2_1)", "a1")
    s11, s21 = num(out, "mag(s_1_1)"), num(out, "mag(s_2_1)")
    check("a valid 2-port still gives the same S-parameters",
          s11 is not None and abs(s11 - 9.0889370933e-01) < 1e-8
          and s21 is not None and abs(s21 - 8.6767895879e-02) < 1e-8,
          "S11=%s S21=%s" % (s11, s21))

    # a genuine port source -- pwr/freq and NO waveform -- must still be a PORT
    out = run("a2\nV1 in 0 dc 0 portnum 1 z0 50 pwr 0.001 freq 1e6\n"
              "R1 in out 50\nR2 out 0 50\n"
              + CTL % "op\nprint @v1[pwr] @v1[freq]", "a2")
    check("a real port source keeps its pwr/freq",
          num(out, "@v1[pwr]") == 0.001 and num(out, "@v1[freq]") == 1e6,
          "pwr=%s freq=%s" % (num(out, "@v1[pwr]"), num(out, "@v1[freq]")))

    # sens's own answer must not move: dv/dR is analytic on a divider
    out = run("a3\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n"
              + CTL % "sens v(out)\nprint r1 v1", "a3")
    r1, v1 = num(out, "r1"), num(out, "v1")
    check("sens still computes the right numbers (dv/dR1 = -2.5e-4, dv/dV1 = 0.5)",
          r1 is not None and abs(r1 + 2.5e-4) < 1e-8
          and v1 is not None and abs(v1 - 0.5) < 1e-8,
          "r1=%s v1=%s" % (r1, v1))

    # a plain transient with no sens anywhere near it
    out = run("a4\n" + RC + CTL % "tran 20n 2u\nprint v(in)[5]", "a4")
    check("a plain transient is unchanged", num(out, "v(in)[5]") is not None
          and abs(num(out, "v(in)[5]") - 2.010484e-02) < 1e-8,
          "v(in)[5]=%s" % num(out, "v(in)[5]"))

    for j in os.listdir(HERE):
        if j.startswith("_ss_") or j == "_rlowdt.osdi":
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
