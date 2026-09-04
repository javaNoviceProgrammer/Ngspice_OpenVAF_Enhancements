#!/usr/bin/env python3
"""Enhancement-519: natures, disciplines and branches, audited against
Accellera VAMS-2023 clauses 3.6-3.13 and Annex D, then fixed.

What this suite pins, each against the quoted clause:

  * 3.11.1 -- the full discipline-compatibility rule set. The LRM's own
    worked example declares electrical and sig_flow_v COMPATIBLE ("the
    nature for flow does not exist in sig_flow_v" -- the Non-Existent
    Binding Rule), a natureless discipline compatible with its whole
    domain, a domainless one with everything. The old rule demanded every
    nature binding both-present-or-both-absent, rejecting exactly those --
    and the mixed branch now takes the discipline that HAS the natures, so
    I(br) across electrical/voltage works, verified numerically. Genuinely
    incompatible pairs (electrical vs rotational) are still rejected.
  * 3.6.1.2 -- the nature-attribute checks were DEAD CODE (they iterated
    the (*...*) annotation accessor, which a nature declaration never has).
    access = "SA" / access = 3.0 ("shall be an identifier") and a
    ddt_nature/idt_nature value that is not a nature name are located
    errors now, instead of being silently dropped. A DERIVED nature
    declaring units warns (the declared value is ignored -- "the derived
    nature always inherits its parent nature units"), and an
    idt_nature/ddt_nature override unrelated to the parent's link warns.
  * Annex D.2 -- constants.vams is the VAMS-2023 file: NIST2018 opt-in
    gives the exact-SI values, the default stays NIST1998, and P_U0 exists
    in both branches. Verified numerically at run time.
  * OSDI 0.4 metadata -- every nature's num_attr claimed one attribute MORE
    than it owns (a consumer walking attr_start..+num_attr read the next
    nature's first attribute). Pinned by dlopen-dumping OSDI_NATURES with
    the committed dump_nda.c harness: ranges are exact and contiguous.
"""

import atexit
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
        if junk.startswith("_lc_"):
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


def compile_file(name):
    osdi = os.path.join(HERE, f"_lc_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def compile_src(src, tag):
    va = os.path.join(HERE, f"_lc_{tag}.va")
    with open(va, "w") as f:
        f.write(src)
    return compile_file(os.path.basename(va))


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_lc_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmdisc\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
                f"option noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def opvar(out, name):
    m = re.search(rf"@n1\[{name}\]\s*=\s*([-+0-9.eE]+)", out)
    return float(m.group(1)) if m else None


HDR = '`include "disciplines.vams"\n'

# ---- 3.11.1: the signal-flow branch, end to end ----------------------------
print("discipline compatibility (LRM 3.11.1):")
rc, out, osdi = compile_file("lrmdisc.va")
check("[1] a branch between electrical and voltage (sig_flow_v) compiles",
      rc == 0, out.strip().splitlines()[-1] if rc else "")
if rc == 0:
    sim = run("N1 a b mm\nV1 a 0 DC 2\nR1 b 0 1k\n.model mm lrmdisc",
              "op\nprint v(b) i(V1)", "sfbr", osdi)
    mv = re.search(r"v\(b\)\s*=\s*([-+0-9.eE]+)", sim, re.I)
    mi = re.search(r"i\(v1\)\s*=\s*([-+0-9.eE]+)", sim, re.I)
    check("[2] the mixed branch behaves as a 1k element: v(b) = 1 V of 2 V",
          mv is not None and abs(float(mv.group(1)) - 1.0) < 1e-9,
          mv.group(1) if mv else None)
    check("[3] I(br) works: the branch took electrical's flow nature (1 mA)",
          mi is not None and abs(float(mi.group(1)) + 1e-3) < 1e-12,
          mi.group(1) if mi else None)

rc, out, _ = compile_src(HDR + """
discipline natureless_c;
  domain continuous;
enddiscipline
module nl(a,b); inout a,b; electrical a; natureless_c b;
  branch (a, b) br;
  analog I(br) <+ V(br)/1e3;
endmodule
""", "natless")
check("[4] a natureless discipline is compatible with its domain (3.11.1)",
      rc == 0, out.strip().splitlines()[-1] if rc else "")

rc, out, _ = compile_src(HDR + """
module rot(a,b); inout a,b; electrical a; rotational b;
  branch (a, b) br;
  analog Theta(br) <+ 1.0;
endmodule
""", "rot")
check("[5] electrical vs rotational stays incompatible",
      rc != 0 and "incompatible disciplines" in out)

# ---- 3.6.1.2: nature-attribute validation is alive again -------------------
print("\nnature attribute forms (LRM 3.6.1.2):")
rc, out, _ = compile_src("""
nature Bad1; access = "SA"; units = "X"; abstol = 1n; endnature
discipline dbad1; flow Bad1; enddiscipline
module m1(a,b); inout a,b; dbad1 a, b;
  analog SA(a,b) <+ 1.0;
endmodule
""", "accstr")
check("[6] access = \"SA\" (a string, not an identifier) is a located error",
      rc != 0 and "access" in out)

rc, out, _ = compile_src("""
nature Bad2; access = NN; units = "X"; abstol = 1n; ddt_nature = 3.0; endnature
discipline dbad2; flow Bad2; enddiscipline
module m2(a,b); inout a,b; dbad2 a, b;
  analog NN(a,b) <+ 1.0;
endmodule
""", "ddtnum")
check("[7] ddt_nature = 3.0 (not a nature name) is a located error",
      rc != 0 and "nature" in out)

rc, out, _ = compile_src(HDR + """
nature FunnyV : Voltage;
  units = "furlong";
  abstol = 1u;
endnature
module m3(a,b); inout a,b; electrical a,b;
  analog I(a,b) <+ V(a,b)/1e3;
endmodule
""", "dunits")
check("[8] units on a DERIVED nature warns that the value is ignored",
      rc == 0 and "units" in out and "ignored" in out.lower())

rc, out, _ = compile_src(HDR + """
nature VoltX : Voltage;
  idt_nature = Temperature;
  abstol = 1u;
endnature
module m4(a,b); inout a,b; electrical a,b;
  analog I(a,b) <+ V(a,b)/1e3;
endmodule
""", "unrel")
check("[9] an idt_nature override unrelated to the parent's link warns",
      rc == 0 and "unrelated" in out)

# Round-4 audit: the other two rules 3.6.1.2 states as illegal used to be
# accepted WITHOUT COMMENT. The derived-access form keeps working (it is the
# deliberate extension the derivednature suite pins) but is now audible; the
# discipline overrides of units/access are illegal AND without effect, and
# both now say so. The LEGAL discipline override (flow.abstol) stays silent.
rc, out, _ = compile_src(HDR + """
nature VoltW : Voltage;
  access = W;
endnature
module m9a(a,b); inout a,b; electrical a,b;
  analog I(a,b) <+ V(a,b)/1e3;
endmodule
""", "dacc")
check("[9b] access on a DERIVED nature warns naming LRM 3.6.1.2",
      rc == 0 and "changes the access attribute" in out and "3.6.1.2" in out)

rc, out, _ = compile_src(HDR + """
discipline dov;
  potential Voltage;
  flow Current;
  flow.units = "mA";
  potential.access = W2;
enddiscipline
module m9b(a,b); inout a,b; electrical a,b;
  analog I(a,b) <+ V(a,b)/1e3;
endmodule
""", "dovr")
check("[9b] a discipline override of units warns that it is ignored",
      rc == 0 and "overrides the flow nature's 'units'" in out)
check("[9b] a discipline override of access warns that it is ignored",
      rc == 0 and "overrides the potential nature's 'access'" in out)

rc, out, _ = compile_src(HDR + """
discipline dab;
  potential Voltage;
  flow Current;
  flow.abstol = 10u;
enddiscipline
module m9c(a,b); inout a,b; electrical a,b;
  analog I(a,b) <+ V(a,b)/1e3;
endmodule
""", "dabs")
check("[9b] the LEGAL abstol override stays warning-free",
      rc == 0 and "warning" not in out)

# Round-4 audit: ...and the legal override now has an EFFECT. 3.6.2.5 lets a
# discipline override an attribute of the nature it binds, 3.6.2.6 makes a
# nature derived from `ttl.flow` inherit it ("abstol = 10u as modified in
# ttl"), and the whole path was dropped: the value was never evaluated, so it
# reached neither `net.flow.<attr>` nor the `.osdi` tables, and the per-node
# convergence tolerance walked a chain that stopped at the discipline. Every
# reading here was the NATURE's own (1e-6 for the first three).
print("\ndiscipline attribute overrides (LRM 3.6.2.5 / 3.6.2.6):")
rc, out, ovr_osdi = compile_file("lrmdisc_ovr.va")
check("[9c] lrmdisc_ovr.va compiles (with only the illegal units warning)",
      rc == 0 and out.count("warning: discipline") == 1,
      out.strip().splitlines()[-1] if rc else "")

if rc == 0:
    sim = run("V1 1 0 DC 1\nV2 2 0 DC 1\nV3 3 0 DC 1\nV4 4 0 DC 1\n"
              "N1 1 2 3 4 mm\n.model mm ovr", "op", "ovr", ovr_osdi)
    m = re.search(r"OVR a_flow=(\S+) a_pot=(\S+) c_flow=(\S+) u_units=(\S+) "
                  r"br_flow=(\S+)", sim)
    got = [m.group(i) for i in range(1, 6)] if m else None
    check("[9c] a discipline's flow.abstol override reaches net.flow.abstol "
          "(1e-5, not the nature's 1e-6)",
          got is not None and abs(float(got[0]) - 1e-5) < 1e-18, f"{got}")
    check("[9c] the potential side, which nothing overrides, is unchanged",
          got is not None and abs(float(got[1]) - 1e-4) < 1e-18, f"{got}")
    check("[9c] a nature derived from ttl.flow inherits the override "
          "(3.6.2.6's own comment: 'abstol = 10u as modified in ttl')",
          got is not None and abs(float(got[2]) - 1e-5) < 1e-18, f"{got}")
    check("[9c] an ILLEGAL units override stays ignored, as its warning says",
          got is not None and got[3] == "A", f"{got}")
    check("[9c] a BRANCH-scoped read sees the override too (br.flow.abstol)",
          got is not None and abs(float(got[4]) - 1e-5) < 1e-18, f"{got}")

    # the solver tolerance: `tight` overrides the POTENTIAL nature's abstol,
    # which is the unknown the convergence test compares, and `tight_derived`
    # reaches the same value through 3.6.2.6. The second node used to report
    # nothing at all, so the circuit-wide default applied.
    dbg = run("V1 1 0 DC 1\nV2 2 0 DC 1\nN2 1 2 mt\n.model mt tol",
              "set ngdebug\nop", "tol", ovr_osdi)
    tols = [float(x) for x in
            re.findall(r"convergence abstol = ([\d.eE+-]+)", dbg)]
    check("[9c] an overridden potential.abstol reaches the convergence test "
          "on both the direct and the derived-nature route",
          len([x for x in tols if abs(x - 1e-9) < 1e-18]) == 2, f"{tols}")

rc, out, _ = compile_src(HDR + """
module vb(a,b); inout a,b;
  electrical [3:5] a; electrical [1:3] b;
  branch (a, b) br1;
  analog I(br1[0]) <+ 1.0;
endmodule
""", "vecbr")
check("[10] vector branches stay rejected with a located diagnostic",
      rc != 0 and "bit-select" in out)

# ---- Annex D.2: the VAMS-2023 constants.vams -------------------------------
print("\nconstants.vams is the VAMS-2023 Annex D.2 file:")
rc, out, osdi = compile_file("lrmdisc_c2023.va")
check("[11] NIST2018 opt-in module compiles", rc == 0)
if rc == 0:
    sim = run("N1 a mm\n.model mm lrmdisc_c2023",
              "op\nprint @n1[pq] @n1[pk] @n1[ph] @n1[pu]", "c23", osdi)
    for name, want, why in [
        ("pq", 1.602176634, "P_Q is the exact-SI 1.602176634e-19"),
        ("pk", 1.380649, "P_K is the exact-SI 1.380649e-23"),
        ("ph", 6.62607015, "P_H is the exact-SI 6.62607015e-34"),
        ("pu", 1.25663706212, "P_U0 is the measured 1.25663706212e-6"),
    ]:
        got = opvar(sim, name)
        check(f"[12] {why}", got is not None and abs(got - want) < 1e-9, f"{got}")

rc, out, osdi = compile_file("lrmdisc_cdef.va")
check("[13] default (no define) module compiles", rc == 0)
if rc == 0:
    sim = run("N1 a mm\n.model mm lrmdisc_cdef",
              "op\nprint @n1[pq] @n1[pu]", "cdef", osdi)
    got = opvar(sim, "pq")
    check("[14] default P_Q stays NIST1998 (1.602176462e-19) per the 2023 LRM",
          got is not None and abs(got - 1.602176462) < 1e-9, f"{got}")
    got = opvar(sim, "pu")
    check("[15] default P_U0 stays 4*pi*1e-7",
          got is not None and abs(got - 1.2566370614359172) < 1e-9, f"{got}")

# ---- OSDI 0.4 nature descriptors: num_attr exact ---------------------------
print("\nOSDI nature descriptors (dlopen dump):")
cc = None
for cand in ("cc", "gcc", "clang"):
    from shutil import which
    if which(cand):
        cc = cand
        break
if cc is None:
    check("[16] (skipped: no C compiler on PATH for the dump harness)", True)
else:
    rc, out, osdi = compile_file("lrmdisc.va")
    exe = os.path.join(HERE, "_lc_dump")
    r = subprocess.run([cc, "-o", exe, os.path.join(HERE, "dump_nda.c")],
                       capture_output=True, text=True, timeout=300)
    check("[16] dump_nda.c compiles", r.returncode == 0, r.stderr.strip()[:80])
    if r.returncode == 0:
        d = subprocess.run([exe, osdi], capture_output=True, text=True,
                           timeout=300).stdout
        cur = re.search(r"nature Current\s+attr_start=(\d+) num_attr=(\d+)", d)
        check("[17] nature Current owns exactly its 4 attributes (was 5)",
              cur is not None and cur.group(2) == "4", cur.groups() if cur else d[:60])
        spans = [(int(a), int(n)) for a, n in
                 re.findall(r"attr_start=(\d+) num_attr=(\d+)", d)]
        total = re.search(r"total_attrs=(\d+)", d)
        ok = bool(spans) and total is not None
        if ok:
            end = 0
            for a, n in spans:
                if a != end:          # contiguous, no overlap, no gap
                    ok = False
                    break
                end = a + n
            # discipline flow/potential override attrs follow the nature
            # region in the same array, so <=, not ==
            ok = ok and end <= int(total.group(1))
        check("[18] every nature's attribute range is contiguous and in-bounds",
              ok, f"{len(spans)} natures")

        # Round-4 audit: the discipline tables carry the LEGAL overrides now
        # that their values are evaluated at all -- and not the illegal ones,
        # which the compiler warns have no effect.
        rc2, _, ovr2 = compile_file("lrmdisc_ovr.va")
        d2 = subprocess.run([exe, ovr2], capture_output=True, text=True,
                            timeout=300).stdout if rc2 == 0 else ""
        ttl = re.search(r"discipline ttl\s.*?\n((?:    .*\n)*)", d2)
        ttlu = re.search(r"discipline ttlu\s.*?\n((?:    .*\n)*)", d2)
        check("[19] the .osdi discipline table carries flow.abstol = 1e-5",
              ttl is not None and "flow.abstol = 1e-05" in ttl.group(1),
              ttl.group(1).strip() if ttl else d2[:60])
        check("[19] ...and not the units override 3.6.1.2 forbids",
              ttlu is not None and "units" not in ttlu.group(1),
              ttlu.group(1).strip() if ttlu else d2[:60])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
