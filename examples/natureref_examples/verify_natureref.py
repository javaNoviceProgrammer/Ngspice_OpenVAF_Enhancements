#!/usr/bin/env python3
"""Enhancement-422: five findings from a round-28 hunt, all in one place --
every reference a `nature` or `discipline` declaration makes to another nature.

  [1] A ONE-CHARACTER TYPO IN A PARENT NATURE NAME CRASHED THE COMPILER.

          nature Vd : Vbaze;      // meant Vbase
            access = V1;
          endnature

      exited 101 with a crash report:

          OpenVAF encountered a problem and has crashed!
          A log file has been generated at ".../openvaf-crash-<ts>.log"
          Panic occurred in file 'openvaf/osdi/src/ndatable.rs' at line 79
          called `Option::unwrap()` on a `None` value

      Nothing validated the name. `hir_ty::lower` resolves it with
      `lookup_nature(..).ok()`, which THROWS THE ERROR AWAY, and OSDI codegen
      then unwrapped the missing name-map entry. Six spellings reached it: a
      typo, an undeclared name, a DISCIPLINE name, an ACCESS FUNCTION name, the
      MODULE name, and a discipline-qualified parent naming a discipline that
      does not exist.

      AND IT DID NOT HAVE TO BE USED. A stray `nature Stray : nosuch;` that no
      discipline and no module ever mentions crashed the build all the same --
      so one bad declaration in an included header killed every model that
      included it.

  [2] THE SIBLING REFERENCES WERE MERELY SILENT.

      `ddt_nature` and `idt_nature` sit two lines away and take the same kind of
      reference. Enhancement-39 hardened THEIR codegen path
      (`unwrap_or(u32::MAX)`) without adding a diagnostic, so a mistyped one was
      quietly discarded and the nature behaved as though it had none. Same
      reference, same mistake, and before this release three different outcomes:
      crash, silence, and (for a discipline's `potential`/`flow`) a complaint
      about the model body. Now one.

  [3] A NATURE INHERITANCE CYCLE WAS SILENT.

      `nature A : A;` and two- and three-nature cycles all compiled. Salsa
      recovers from the query cycle by re-resolving with the parent dropped, so
      nothing crashes and nothing is said -- the nature just silently becomes
      its own base nature, inherits no units, AND THEREFORE CHANGES WHICH
      DISCIPLINES IT IS COMPATIBLE WITH (compatibility falls back to the
      same-base-nature rule when units are absent, per Enhancement-399).

      Parameter cycles, `aliasparam` cycles (Enhancement-414) and analog-function
      recursion are all rejected by name. Nature cycles were the family member
      nobody checked.

  [4] `abstol` WAS UNVALIDATED, IN TWO DIFFERENT WAYS.

      `abstol = 0`, a negative abstol, and a literal that overflows to infinity
      (`1e400`) all compiled and reached the OSDI nature descriptor. abstol is
      the size below which the solver stops distinguishing two values; none of
      those is a usable tolerance.

      And separately: an abstol whose value is not a folded real constant --
      `1.0/0.0`, `0.0/0.0`, `1e-6+0.0`, even `"abc"` -- was SILENTLY DISCARDED,
      leaving the nature with no abstol at all, which is not what the
      declaration says. Both halves are checked; a nature with no `abstol`
      attribute remains perfectly legal.

  [5] A DISCIPLINE WHOSE `potential`/`flow` NAMED A MISSING NATURE COMPLAINED
      ABOUT THE MODEL BODY.

      The old message was "illegal access of branch '(p, p)'" -- which names
      neither the discipline nor the missing nature, and points at a line that
      is not wrong. Now it is reported at the declaration.

THE HARNESS LESSON, recorded because it hid [1] for two whole rounds: openvaf
installs a panic HOOK. A hard compiler crash exits **101** with a polite banner
containing NEITHER the word "panicked" NOR a backtrace. A crash detector keyed
on signals (negative rc) or on "panicked" in the output scores it as an ordinary
rejection -- which is exactly why rounds 26 and 27 both reported "no crashes".
The check below asserts the crash banner is GONE, not merely that rc != 0.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0
HDR = '`include "disciplines.vams"\n'

# a well-formed pair of natures and a discipline built from them
BASE = """nature Vbase;
  units = "V"; access = Vb; abstol = 1e-6;
endnature
nature Ibase;
  units = "A"; access = Ib; abstol = 1e-12;
endnature
discipline d1;
  potential Vbase; flow Ibase;
enddiscipline
"""
BODY = ("module dut(p, n);\n inout p, n; d1 p, n;\n"
        " analog Ib(p, n) <+ 1e-3*Vb(p, n);\nendmodule\n")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(src, tag):
    d = os.path.join(HERE, "_nr_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def crashed(rc, out):
    """openvaf's panic hook exits 101 with a banner and no backtrace."""
    return (rc < 0 or "has crashed" in out or "openvaf-crash" in out
            or "panicked" in out)


def rejected(label, src, tag, needle):
    """A clean diagnostic: non-zero rc, the expected text, and NO crash."""
    _, rc, out = build(src, tag)
    ok = rc != 0 and needle in out and not crashed(rc, out)
    check(label, ok, f"rc={rc} " + (out.strip().splitlines() or ["no output"])[0][:74])


def clean(label, src, tag):
    _, rc, out = build(src, tag)
    noisy = [l for l in out.splitlines() if l.startswith(("error", "warning"))]
    check(label, rc == 0 and not noisy, f"rc={rc} " + (noisy or [""])[0][:70])


def nat(parent="Vbase", extra="", name="Vd"):
    return BASE + f"nature {name} : {parent};\n access = V1;{extra}\nendnature\n"


def main():
    # =====================================================================
    print("\n[1] a parent nature that does not resolve -- was a COMPILER CRASH")
    NOTANAT = "which is not a nature"
    for tag, parent, note in [
        ("typo",   "Vbaze",  "a one-character typo"),
        ("undecl", "nosuch", "a name that was never declared"),
        ("disc",   "d1",     "a DISCIPLINE name"),
        ("access", "Vb",     "an ACCESS FUNCTION name"),
        ("module", "dut",    "the MODULE name"),
    ]:
        rejected(f"parent = {parent} ({note}) is a clean error, not a crash",
                 HDR + nat(parent) + BODY, "p_" + tag, NOTANAT)
    rejected("a discipline-qualified parent naming a missing discipline",
             HDR + nat("nosuchdisc.potential") + BODY, "p_qual", NOTANAT)

    # THE BLAST RADIUS: it did not have to be used
    rejected("a STRAY nature that nothing references is still reported (not a crash)",
             HDR + BASE + "nature Stray : nosuch;\n access = Sx;\nendnature\n" + BODY,
             "p_stray", NOTANAT)

    # the crash banner must be gone, explicitly -- rc != 0 is not enough
    _, rc, out = build(HDR + nat("Vbaze") + BODY, "p_banner")
    check("the crash report is gone (rc=101 + banner, which a naive detector misses)",
          not crashed(rc, out) and "openvaf-crash" not in out and rc == 65,
          f"rc={rc}")
    check("...and no crash log was written",
          not any(f.startswith("openvaf-crash")
                  for f in os.listdir(os.path.join(HERE, "_nr_p_banner"))))

    # ---- accept half ----------------------------------------------------
    clean("a correctly spelled parent", HDR + nat("Vbase") + BODY, "p_ok")
    clean("a discipline-qualified parent that resolves (d1.flow)",
          HDR + nat("d1.flow") + BODY, "p_ok2")
    clean("a three-deep parent chain",
          HDR + BASE + "nature L1 : Vbase;\n access = A1;\nendnature\n"
          "nature L2 : L1;\n access = A2;\nendnature\n"
          "nature L3 : L2;\n access = A3;\nendnature\n" + BODY, "p_ok3")
    clean("a nature with no parent at all", HDR + BASE + BODY, "p_ok4")

    # =====================================================================
    print("\n[2] ddt_nature / idt_nature -- the sibling that merely went silent")
    for tag, attr, note in [
        ("idt",  "idt_nature = nosuch;",  "idt_nature naming nothing"),
        ("ddt",  "ddt_nature = nosuch;",  "ddt_nature naming nothing"),
        ("disc", "idt_nature = d1;",      "idt_nature naming a discipline"),
        ("acc",  "idt_nature = Vb;",      "idt_nature naming an access function"),
        ("qual", "idt_nature = nosuchdisc.potential;", "a missing discipline, qualified"),
    ]:
        rejected(f"{note} is reported", HDR + nat(extra=" " + attr) + BODY,
                 "s_" + tag, NOTANAT)
    clean("idt_nature naming a real nature", HDR + nat(extra=" idt_nature = Ibase;") + BODY,
          "s_ok")
    clean("ddt_nature naming a real nature", HDR + nat(extra=" ddt_nature = Ibase;") + BODY,
          "s_ok2")
    clean("a discipline-qualified ddt_nature that resolves",
          HDR + nat(extra=" ddt_nature = d1.flow;") + BODY, "s_ok3")

    # =====================================================================
    print("\n[3] nature inheritance cycles")
    CYC = "inherits from itself"
    rejected("a nature derived from ITSELF",
             HDR + BASE + "nature nA : nA;\n access = Aa;\nendnature\n" + BODY, "c_self", CYC)
    rejected("a two-nature cycle",
             HDR + BASE + "nature nA : nB;\n access = Aa;\nendnature\n"
             "nature nB : nA;\n access = Bb;\nendnature\n" + BODY, "c_two", CYC)
    rejected("a three-nature cycle",
             HDR + BASE + "nature nA : nB;\n access = Aa;\nendnature\n"
             "nature nB : nC;\n access = Bb;\nendnature\n"
             "nature nC : nA;\n access = Cc;\nendnature\n" + BODY, "c_three", CYC)
    _, rc, out = build(HDR + BASE + "nature nA : nA;\n access = Aa;\nendnature\n" + BODY,
                       "c_chain")
    check("the diagnostic prints the cycle", "cycle: nA -> nA" in out,
          [l.strip() for l in out.splitlines() if "cycle:" in l][:1])
    clean("a long ACYCLIC chain is not mistaken for a cycle",
          HDR + BASE + "nature k1 : Vbase;\n access = K1;\nendnature\n"
          "nature k2 : k1;\n access = K2;\nendnature\n"
          "nature k3 : k2;\n access = K3;\nendnature\n"
          "nature k4 : k3;\n access = K4;\nendnature\n" + BODY, "c_ok")

    # the consequence the diagnostic claims: a broken parent changes compatibility
    def two_disc(parent):
        return (HDR + BASE + f"nature Vd1 : {parent};\n access = V1;\nendnature\n"
                "nature Vd2 : Vbase;\n access = V2;\nendnature\n"
                "discipline da;\n potential Vd1; flow Ibase;\nenddiscipline\n"
                "discipline db;\n potential Vd2; flow Ibase;\nenddiscipline\n"
                "module dut(p, n);\n inout p, n;\n da p;\n db n;\n"
                " analog Ib(p, n) <+ 1e-3*V1(p, n);\nendmodule\n")
    clean("two disciplines sharing ONE base nature are compatible", two_disc("Vbase"), "k_ok")
    _, rc, out = build(two_disc("Vbaze"), "k_bad")
    check("a broken parent DID change compatibility -- now the typo is named first",
          rc != 0 and "which is not a nature" in out,
          [l.strip() for l in out.splitlines() if l.startswith("error")][:1])

    # =====================================================================
    print("\n[4] abstol")
    def ab(val):
        return (HDR + f'nature Vbase;\n units = "V"; access = Vb; abstol = {val};\nendnature\n'
                'nature Ibase;\n units = "A"; access = Ib; abstol = 1e-12;\nendnature\n'
                "discipline d1;\n potential Vbase; flow Ibase;\nenddiscipline\n" + BODY)
    BAD = "which is not a usable absolute tolerance"
    for val, note in [("0.0", "zero"), ("-1e-6", "negative"), ("-1.0", "large negative"),
                      ("1e400", "a literal that overflows to +inf"),
                      ("-1e400", "and to -inf")]:
        rejected(f"abstol = {val} ({note}) is rejected", ab(val), "a_" + re.sub(r"\W", "", val), BAD)
    NOTC = "not a real constant"
    for val, note in [("1.0/0.0", "an expression (would be inf)"),
                      ("0.0/0.0", "an expression (would be NaN)"),
                      ("1e-6+0.0", "an expression that is perfectly sane"),
                      ('"abc"', "a STRING")]:
        rejected(f"abstol = {val} ({note}) -- silently discarded before -- is rejected",
                 ab(val), "n_" + re.sub(r"\W", "", val), NOTC)
    for val in ("1e-6", "1e-12", "1.0", "1e-30"):
        clean(f"abstol = {val} is accepted", ab(val), "ao_" + re.sub(r"\W", "", val))
    clean("a nature with NO abstol attribute at all stays legal",
          HDR + 'nature Vbase;\n units = "V"; access = Vb;\nendnature\n'
          'nature Ibase;\n units = "A"; access = Ib; abstol = 1e-12;\nendnature\n'
          "discipline d1;\n potential Vbase; flow Ibase;\nenddiscipline\n" + BODY, "a_none")

    # =====================================================================
    print("\n[5] a discipline naming a nature that does not exist")
    for tag, pot, flow, note in [
        ("pot",  "nosuchnature", "Ibase",        "potential"),
        ("flow", "Vbase",        "nosuchnature", "flow"),
        ("both", "nosuchp",      "nosuchf",      "both"),
    ]:
        src = (HDR + 'nature Vbase;\n units = "V"; access = Vb; abstol = 1e-6;\nendnature\n'
               'nature Ibase;\n units = "A"; access = Ib; abstol = 1e-12;\nendnature\n'
               f"discipline d1;\n potential {pot}; flow {flow};\nenddiscipline\n" + BODY)
        rejected(f"a discipline whose {note} names a missing nature is reported "
                 f"at the DECLARATION", src, "d_" + tag, "which is not a nature")
    _, rc, out = build(HDR + 'nature Vbase;\n units = "V"; access = Vb; abstol = 1e-6;\nendnature\n'
                       'nature Ibase;\n units = "A"; access = Ib; abstol = 1e-12;\nendnature\n'
                       "discipline d1;\n potential nosuchnature; flow Ibase;\nenddiscipline\n"
                       + BODY, "d_msg")
    # The old body-level complaint still CASCADES from the same root cause. What
    # changed is which one comes FIRST: the declaration error now leads, naming
    # the discipline and the missing nature. Suppressing the cascade would mean
    # teaching the body walk that the discipline is already broken, which is a
    # wider change than the evidence asks for -- so the ordering is what is
    # pinned, and the cascade is recorded rather than hidden.
    errs = [l.strip() for l in out.splitlines() if l.startswith("error:")]
    check("...and that error comes FIRST, naming the discipline and the missing nature",
          errs and "discipline 'd1'" in errs[0] and "nosuchnature" in errs[0],
          errs[:1])
    check("the note points at the discipline, not at 'the nature'",
          "the discipline has no potential nature" in out,
          [l.strip() for l in out.splitlines() if "discipline has no" in l][:1])

    # =====================================================================
    print("\n[6] the standard library and a real model must be untouched")
    clean("a plain electrical model on the stock disciplines.vams",
          HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
          " analog I(p, n) <+ 1e-3*V(p, n);\nendmodule\n", "z_std")
    clean("a model using thermal + electrical (two stock disciplines)",
          HDR + "module dut(p, n, t);\n inout p, n, t;\n electrical p, n;\n thermal t;\n"
          " analog begin\n  I(p, n) <+ 1e-3*V(p, n);\n"
          "  Pwr(t) <+ 1e-3*V(p, n)*V(p, n);\n end\nendmodule\n", "z_two")
    clean("a user nature derived from a STOCK one",
          HDR + "nature MyVoltage : Voltage;\n access = MyV;\nendnature\n"
          "discipline myelec;\n potential MyVoltage; flow Current;\nenddiscipline\n"
          "module dut(p, n);\n inout p, n; myelec p, n;\n"
          " analog I(p, n) <+ 1e-3*MyV(p, n);\nendmodule\n", "z_derive")

    # and it must still SIMULATE
    d, rc, _ = build(HDR + BASE + BODY, "z_sim")
    open(os.path.join(d, "q.cir"), "w").write(
        "* sim\nV1 a 0 dc 1\nN1 a 0 dut\n.model dut dut()\n"
        ".control\npre_osdi m.osdi\noption noacct\nset numdgt=12\nop\nprint i(v1)\n.endc\n.end\n")
    r = subprocess.run(["perl", "-e", "alarm 40; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    m = re.search(r"^i\(v1\)\s*=\s*(\S+)", r.stdout + r.stderr, re.M)
    got = float(m.group(1)) if m else None
    check("a model built on custom natures still simulates (i = -1 mA)",
          got is not None and abs(got + 1e-3) < 1e-12, f"i(v1)={got}")

    for j in os.listdir(HERE):
        if j.startswith("_nr_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
