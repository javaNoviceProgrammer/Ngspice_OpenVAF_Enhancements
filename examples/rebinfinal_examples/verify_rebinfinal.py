#!/usr/bin/env python3
"""Enhancements 826 to 828 (F10-F12 of the 2026-10-08 ngspice + OSDI hunt):
`alter` of a binned instance's size, the message of a failed Verilog-A compile,
and `@(final_step)` under pss and hb.

Enhancement-826 (F10). `alter n1 l=5u` on an OSDI instance bound to nch.1
(l in [0, 1u)) left it on nch.1 with nch.2's size, and the old current, in
silence: ngspice re-binned only m-devices. A size no bin covers was applied
too, after a bare "no model available", for a built-in BSIM card as well.
  [1] the instance moves to the bin that covers the new size, and back; a
      size no bin covers is refused (the bins named, the value not applied);
      built-in BSIM4 bins; a model that is not binned (control)

Enhancement-827 (F11). Every failed compile under `pre_osdi -va` was answered
with advice on where to put the compiler, including a compiler that ran and
printed the source's error; `pre_snp` also printed the raw wait status
("exit 32512").
  [2] a source error points at the compiler's messages; a compiler that is
      not there, not on PATH or not executable gets the advice; pre_snp too

Enhancement-828 (F12). pss and hb fired @(initial_step) and never
@(final_step).
  [3] each fires it once, at the end of the period, seeing the steady state:
      pss its own last time point, hb the sum of its harmonics at t = T; tran
      and qpss (controls)
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

WORK = tempfile.mkdtemp(prefix="rebinfinal_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    return ok


def write(name, text):
    path = os.path.join(WORK, name)
    with open(path, "w") as f:
        f.write(text)
    return path


def compile_va(name, src):
    va = write(name + ".va", src)
    r = subprocess.run([VAF, va, "-o", os.path.join(WORK, name + ".osdi")],
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)


def run(name, deck, env=None):
    path = write(name, deck)
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300,
                       cwd=WORK, errors="replace", env=env)
    return p.stdout + p.stderr


def vals(out, name):
    return [float(x.rstrip(",")) for x in re.findall(r"^" + re.escape(name) + r" = (\S+)", out, re.M)]


def near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol * max(1e-12, abs(b))


H = '`include "disciplines.vams"\n'
print("Enhancements 826-828: binned alter, compile failures, final step under pss and hb\n")

# ------------------------------------------------------------- [1] ---
print("[1] Enhancement-826: alter re-bins any binned instance")
compile_va("bm", H + """module bm(a, b);
inout a, b; electrical a, b;
parameter real g = 1e-3;
parameter real lmin = 0; parameter real lmax = 1;
parameter real wmin = 0; parameter real wmax = 1;
(* type="instance" *) parameter real l = 1e-6;
(* type="instance" *) parameter real w = 1e-6;
analog I(a,b) <+ g*V(a,b);
endmodule
""")
BINS = (".model nch.1 bm g=1m lmin=0 lmax=1u wmin=0 wmax=10u\n"
        ".model nch.2 bm g=3m lmin=1u lmax=10u wmin=0 wmax=10u\n")
out = run("bin1.cir", f"* bins\n.control\npre_osdi bm.osdi\n.endc\nv1 1 0 1\nv2 2 0 1\n"
          f"n1 1 0 nch l=0.5u w=1u\nn2 2 0 nch l=0.5u w=1u\n{BINS}"
          ".control\nop\nprint i(v1)\nalter n1 l=5u\nop\nprint i(v1)\nprint i(v2)\n"
          "alter n1 l=50u\nop\nprint i(v1)\nprint @n1[l]\n"
          "alter n1 l=0.5u\nop\nprint i(v1)\n"
          "alter n2 l=5u\nalter n1 l=5u\nop\nprint i(v1)\nprint i(v2)\n.endc\n.end\n")
i1, i2 = vals(out, "i(v1)"), vals(out, "i(v2)")
check("[1] `alter n1 l=5u` (nch.1 covers l < 1u): n1 moves to nch.2, said so, i(v1) = -3 mA; "
      "n2 stays on nch.1 (was -1 mA, no word)",
      len(i1) >= 2 and near(i1[0], -1e-3) and near(i1[1], -3e-3) and near(i2[0], -1e-3)
      and "Notice: model has changed from nch.1 to nch.2." in out, f"{i1} {i2}")
check("[1] `alter n1 l=50u` (no bin covers it): refused, the bins named, l stays 5u and the "
      "current 3 mA (was applied)",
      "none covers this instance's l=5e-05" in out and "not applied: n1 keeps the size it had" in out
      and vals(out, "@n1[l]") == [5e-6] and len(i1) >= 3 and near(i1[2], -3e-3), f"{i1} {out[-400:]}")
check("[1] back to l=0.5u: nch.1 again, -1 mA; both instances to 5u: nch.1 is left empty and "
      "both read -3 mA",
      len(i1) == 5 and near(i1[3], -1e-3) and near(i1[4], -3e-3) and len(i2) == 2
      and near(i2[1], -3e-3) and "Notice: model has changed from nch.2 to nch.1." in out, f"{i1} {i2}")

out = run("bin2.cir", "* built-in bsim4 bins\nvd d 0 1\nvg g 0 1\nm1 d g 0 0 nch l=0.5u w=1u\n"
          ".model nch.1 nmos level=54 version=4.8.2 lmin=0 lmax=1u wmin=0 wmax=10u vth0=0.3\n"
          ".model nch.2 nmos level=54 version=4.8.2 lmin=1u lmax=10u wmin=0 wmax=10u vth0=0.6\n"
          ".control\nop\nprint i(vd)\nalter m1 l=5u\nop\nprint i(vd)\nalter m1 l=50u\nop\n"
          "print i(vd)\nprint @m1[l]\n.endc\n.end\n")
iv = vals(out, "i(vd)")
check("[1] built-in BSIM4 bins: `alter m1 l=5u` moves m1 to nch.2 (control: it did before)",
      "Notice: model has changed from nch.1 to nch.2." in out and len(iv) == 3
      and abs(iv[1]) < abs(iv[0]) / 10, f"{iv}")
check("[1] ...and `alter m1 l=50u` is refused, l stays 5u and the current with it "
      "(was 'no model available', then applied: l = 50u on nch.2)",
      "not applied: m1 keeps the size it had" in out and vals(out, "@m1[l]") == [5e-6]
      and len(iv) == 3 and near(iv[2], iv[1]), f"{iv} {vals(out, '@m1[l]')}")

out = run("bin3.cir", "* not binned\n.control\npre_osdi bm.osdi\n.endc\nv1 1 0 1\n"
          "n1 1 0 one l=0.5u w=1u\n.model one bm g=2m\n.control\nalter n1 l=5u\nop\nprint i(v1)\n"
          "print @n1[l]\n.endc\n.end\n")
check("[1] a model that is not binned (control): `alter n1 l=5u` applies, no notice",
      vals(out, "@n1[l]") == [5e-6] and near(vals(out, "i(v1)")[0] if vals(out, "i(v1)") else None, -2e-3)
      and "Notice" not in out and "rror" not in out, out[-300:])

# ------------------------------------------------------------- [2] ---
print("[2] Enhancement-827: a failed compile says why")
write("bad.va", H + "module bad(a, b);\ninout a, b; electrical a, b;\nanalog I(a,b) <+ nosuch*V(a,b);\nendmodule\n")
BADDECK = "* bad va\n.control\npre_osdi -va bad.va\n.endc\nv1 1 0 1\n.control\nop\n.endc\n.end\n"
ADVICE = "Set the compiler with `set openvaf=/path/to/openvaf-r`"

out = run("bad1.cir", BADDECK, dict(os.environ, OPENVAF=VAF))
check("[2] a source error (the compiler ran, exit 65): 'could not compile .../bad.va (exit 65); its "
      "messages above say why', no advice on where to put the compiler",
      re.search(r"could not compile \S*bad\.va \(exit 65\); its messages above", out) and ADVICE not in out
      and "'nosuch' was not found" in out, out[-500:])

out = run("bad2.cir", BADDECK, dict(os.environ, OPENVAF=os.path.join(WORK, "nosuch", "openvaf-r")))
check("[2] a compiler named by a path that does not exist: 'could not run the compiler ... (no such "
      "file)' and the advice",
      "could not run the compiler" in out and "(no such file)" in out and ADVICE in out, out[-400:])

out = run("bad3.cir", BADDECK, dict(os.environ, OPENVAF="openvaf-r-nosuch"))
check("[2] a bare name not on PATH: '(not on PATH)' and the advice",
      "(not on PATH)" in out and ADVICE in out, out[-400:])

noexec = write("noexec", "#!/bin/sh\nexit 0\n")
os.chmod(noexec, 0o644)
out = run("bad4.cir", BADDECK, dict(os.environ, OPENVAF=noexec))
if sys.platform.startswith("win"):
    check("[2] a compiler that is not executable (skipped on Windows: no execute bit)", True)
else:
    check("[2] a compiler file that is not executable: '(not executable)' and the advice",
          "(not executable)" in out and ADVICE in out, out[-400:])

# a matched two-port attenuator, written here: the touchstone suite's _r2.s2p
# is generated by that suite, which runs after this one in a sweep
write("t.s2p", "! a matched 2-port attenuator\n# GHz S MA R 50\n"
               "1 0.1 0 0.5 0 0.5 0 0.1 0\n2 0.1 0 0.5 0 0.5 0 0.1 0\n3 0.1 0 0.5 0 0.5 0 0.1 0\n")
out = run("snp.cir", "* snp\n.control\npre_snp t.s2p\n.endc\nv1 1 0 1\n.control\nop\n.endc\n.end\n",
          dict(os.environ, OPENVAF=os.path.join(WORK, "nosuch", "openvaf-r")))
check("[2] pre_snp with a compiler that does not exist: the same report (was 'exit 32512', the raw "
      "wait status)",
      "pre_snp: could not run the compiler" in out and "(no such file)" in out and "32512" not in out,
      out[-400:])

# ------------------------------------------------------------- [3] ---
print("[3] Enhancement-828: @(final_step) under pss and hb")
compile_va("pc", H + """module pc(a, b);
inout a, b; electrical a, b;
integer ninit, nfin;
analog begin
  @(initial_step) ninit = ninit + 1;
  I(a,b) <+ V(a,b)/1k + 1e-4*V(a,b)*V(a,b);
  @(final_step) begin nfin = nfin + 1; $strobe("FINAL init=%0d fin=%0d V=%.6f", ninit, nfin, V(a,b)); end
end
endmodule
""")
DRIVEN = "V1 a 0 SIN(0 1 1meg)\nR1 a b 1k\nC1 b 0 1n\nn1 b 0 pcm\n.model pcm pc\n"


def finals(out):
    return [(int(a), int(b), float(c)) for a, b, c in re.findall(r"FINAL init=(\d+) fin=(\d+) V=(\S+)", out)]


out = run("pss.cir", f"* pss\n.control\npre_osdi pc.osdi\n.endc\n{DRIVEN}.pss 1meg 1u b 1024 10 50 5u\n"
          ".control\nrun\nsetplot pss1\nset numdgt=8\nprint v(b)[length(v(b))-1]\n.endc\n.end\n")
f = finals(out)
m = re.search(r"v\(b\)\[length\(v\(b\)\)-1\] = (\S+)", out)
vend = float(m.group(1)) if m else None
check("[3] pss: @(final_step) once after one initial step (was never), at the end of the period: "
      "the value its own time-domain plot ends on",
      len(f) == 1 and f[0][:2] == (1, 1) and vend is not None and abs(f[0][2] - vend) < 1e-5,
      f"{f} {vend}")

out = run("hb.cir", f"* hb\n.control\npre_osdi pc.osdi\n.endc\n{DRIVEN}.control\nhb 1meg 8\n"
          "set numdgt=10\nprint real(b)\n.endc\n.end\n")
f = finals(out)
reals = [float(x) for x in re.findall(r"^\d+\t(\S+)\s*$", out, re.M)]
check("[3] hb: @(final_step) once (was never), seeing the steady state at t = T: the sum of the real "
      "parts of b's harmonics, -0.14515 V",
      len(f) == 1 and f[0][:2] == (1, 1) and len(reals) == 9 and abs(f[0][2] - sum(reals)) < 2e-6
      and abs(f[0][2] + 0.14515) < 1e-4, f"{f} {sum(reals) if reals else None}")

out = run("tran.cir", f"* tran\n.control\npre_osdi pc.osdi\n.endc\n{DRIVEN}.control\ntran 1n 2u\n.endc\n.end\n")
check("[3] tran (control): one final step", [x[:2] for x in finals(out)] == [(1, 1)], out[-300:])

out = run("qpss.cir", f"* qpss\n.control\npre_osdi pc.osdi\n.endc\n{DRIVEN}V2 c 0 SIN(0 0.1 1.1meg)\n"
          "R3 c b 1k\n.control\nqpss v(b) 1meg 1.1meg\n.endc\n.end\n")
check("[3] qpss (control): one final step", [x[:2] for x in finals(out)] == [(1, 1)], out[-300:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
