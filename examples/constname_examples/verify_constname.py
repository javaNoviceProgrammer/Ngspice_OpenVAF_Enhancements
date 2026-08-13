#!/usr/bin/env python3
"""Enhancement-448: a node name that collides with a built-in constant.

ngspice keeps a permanent `const` plot holding twelve vectors -- c, e, i, pi,
kelvin, boltz, echarge, planck, TRUE, FALSE, yes and no -- and vec_get() falls
back to it when the current plot has no such vector. Three consequences, all
fixed here, each pinned against a control that must NOT move:

  * v(c) named a NODE, so a constant is never a valid answer. It used to
    return 2.9979e+08 for a node that had been renamed or mistyped, which
    `sweep` drew as a flat curve and which defeated Enhancement-431's
    "-output never resolved" refusal.
  * c[0] is the literal name of a bus bit -- exactly what `.option autobus`
    (Enhancement-444) builds for a bus called `c`. Enhancement-224 preferred
    that literal name only when nothing called `c` existed, so every bit of
    such a bus was unreachable while `print all` printed it correctly.
  * a BARE name is genuinely ambiguous and still resolves to the constant,
    but no longer in silence when a vector of that name exists elsewhere.
"""
import os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
NGSPICE = os.environ.get(
    "NGSPICE_BIN",
    os.path.join(HERE, "..", "..", "ngspice-46", "build", "src", "ngspice"))
CONSTS = ("c", "e", "i", "pi", "kelvin", "boltz", "echarge", "planck",
          "TRUE", "FALSE", "yes", "no")

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(body, ctl, tag, cards="", timeout=120):
    deck = (f"constname {tag}\n{body}\n{cards}\n.control\noption noacct\n"
            f"set numdgt=8\n{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_cn_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    return r.returncode, r.stdout + r.stderr


def last(out):
    m = re.findall(r"=\s*(-?[\d.]+(?:e[-+]?\d+)?)", out)
    return m[-1] if m else None


def near(s, want, tol=1e-6):
    try:
        return s is not None and abs(float(s) - want) <= tol * max(1.0, abs(want))
    except (TypeError, ValueError):
        return False


# node `c` -> 0.5 ; node `coll` -> 0.5 (no node named c) ; node `c[0]` -> 0.5
DIV_C = "V1 a 0 dc 1\nRs a c 1k\nR1 c 0 1k"
DIV_NC = "V1 a 0 dc 1\nRs a coll 1k\nR1 coll 0 1k"
DIV_C0 = "V1 a 0 dc 1\nRs a c[0] 1k\nR1 c[0] 0 1k"
DIV_Q0 = "V1 a 0 dc 1\nRs a q[0] 1k\nR1 q[0] 0 1k"
# a scalar node `q` (0.75) AND a bus bit `q[0]` (0.50) in one circuit
BOTH = "V1 in 0 dc 1\nRq in q 1k\nRq2 q 0 3k\nRb in q[0] 1k\nRb2 q[0] 0 1k"
NUM = "V1 1 0 dc 1\nR1 1 2 1k\nR2 2 0 1k"

print("Enhancement-448: node names that collide with built-in constants\n")

# ----------------------------------------------------- the constants work ---
# THE control set: every fix narrows what a name may mean, so ordinary use of
# the constant plot has to be bit-for-bit unchanged.
print("the constant plot still works (controls)")
for name, want in (("pi", 3.14159265), ("c", 2.997925e8), ("boltz", 1.380649e-23),
                   ("echarge", 1.602177e-19), ("kelvin", -273.15), ("no", 0.0),
                   ("yes", 1.0), ("TRUE", 1.0), ("planck", 6.62607e-34)):
    rc, out = run(DIV_NC, f"op\nprint {name}", f"k{name}")
    check(f"[E-448] bare `{name}` still reads the constant",
          rc == 0 and near(last(out), want, 1e-4), f"{last(out)}")

rc, out = run(DIV_NC, "op\nlet x=2*pi\nprint x", "expr")
check("[E-448] a constant still works inside an expression",
      rc == 0 and near(last(out), 6.28318531, 1e-6), f"{last(out)}")
rc, out = run(DIV_NC, "op\nlet y=boltz*2\nprint y", "expr2")
check("[E-448] ...and after an analysis has run",
      rc == 0 and near(last(out), 2.761297e-23, 1e-4), f"{last(out)}")
# No analysis at all: ngspice exits 1 for a deck that never runs one, which has
# nothing to do with the constant -- assert the VALUE only.
rc, out = run(DIV_NC, "print pi", "nockt")
check("[E-448] ...and with no analysis at all",
      near(last(out), 3.14159265, 1e-6), f"{last(out)}")

# --------------------------------------------------------- v(X) is a node ---
print("\nv(X) names a node, so it never answers with a constant")
rc, out = run(DIV_C, "op\nprint v(c)", "vc_node")
check("[E-448] v(c) reads the NODE when one exists",
      rc == 0 and near(last(out), 0.5), f"{last(out)}")
for name in CONSTS:
    rc, out = run(DIV_NC, f"op\nprint v({name})", f"vc_{name}")
    check(f"[E-448] v({name}) with no such node is refused, not answered",
          "no such vector" in out and not re.search(r"=\s*2\.99", out),
          f"{[l.strip() for l in out.splitlines() if 'Error' in l][:1]}")

# ------------------------------------------- ...including through `sweep` ---
print("\nsweep -output: Enhancement-431's refusal is no longer bypassed")
rc, out = run(DIV_NC, "op\nsweep R1 1k 5k 2k -output vo=v(c)", "sw_c")
check("[E-448] `-output v(c)` is refused, not drawn as a flat 3e8 curve",
      "never resolved" in out and "2.99792458e+08" not in out)
rc, out = run(DIV_NC, "op\nsweep R1 1k 5k 2k -output vo=v(no)", "sw_no")
check("[E-448] `-output v(no)` is refused too (it drew a flat 0.0)",
      "never resolved" in out)
rc, out = run(DIV_C, "op\nsweep R1 1k 5k 2k -output vo=v(c)\nprint vo", "sw_ok")
vals = [m[1] for m in re.findall(r"^\s*(\d+)\t(\S+)", out, re.M)]
check("[E-448] a REAL node named c still sweeps correctly (control)",
      rc == 0 and len(vals) == 3 and near(vals[0], 0.5) and near(vals[2], 0.8333333, 1e-5),
      f"{vals}")

# ------------------------------------------------------- bracketed names ---
print("\na bus bit named after a constant is reachable")
for name in CONSTS:
    body = f"V1 a 0 dc 1\nRs a {name}[0] 1k\nR1 {name}[0] 0 1k"
    rc, out = run(body, f"op\nprint {name}[0]", f"b_{name}")
    rc2, out2 = run(body, f"op\nprint v({name}[0])", f"bv_{name}")
    check(f"[E-448] node {name}[0] reads through both `{name}[0]` and `v({name}[0])`",
          rc == 0 and near(last(out), 0.5) and rc2 == 0 and near(last(out2), 0.5),
          f"{last(out)} / {last(out2)}")

rc, out = run(DIV_Q0, "op\nprint q[0]", "e224a")
rc2, out2 = run(DIV_Q0, "op\nprint v(q[0])", "e224b")
check("[E-448] Enhancement-224's ordinary array node still works (control)",
      near(last(out), 0.5) and near(last(out2), 0.5), f"{last(out)} / {last(out2)}")

rc, out = run(DIV_C0, "op\nprint \"c[0]\"", "quoted")
check("[E-448] Enhancement-433's quoting still reaches it (control)",
      rc == 0 and near(last(out), 0.5), f"{last(out)}")

# ---------------------------------- the silent case: base is a LONG vector ---
print("\na node and a bus bit sharing a base name: the node wins, and says so")
rc, out = run(BOTH, "op\nprint v(q[0])", "both_op")
check("[E-448] v(q[0]) reads the bus bit (0.50), not node q (0.75)",
      rc == 0 and near(last(out), 0.5), f"{last(out)}")
rc, out = run(BOTH, "tran 1u 5u\nprint q[0]", "both_tran")
rows = len(re.findall(r"^\s*\d+\t", out, re.M))
check("[E-448] in tran it is the bus bit's WAVEFORM, not q's first sample",
      rc == 0 and rows > 2, f"{rows} rows")
check("[E-448] ...and the ambiguity is reported, not silent",
      "is itself a vector" in out)

# --------------------------------------------------- the real-world path ---
# `.option autobus` (Enhancement-444) GENERATES these node names: a bus port
# called `c` becomes the nodes c[0]..c[4]. Every bit of such a bus used to be
# unreadable while the circuit solved correctly around it. The same deck with
# the bus called `a` is the reference -- the two must agree bit for bit.
print("\n.option autobus with a bus named after a constant (Enhancement-444)")
OPENVAF = os.environ.get("OPENVAF_BIN", "openvaf-r")
osdi_ok = subprocess.run([OPENVAF, "constbus.va", "-o", "constbus.osdi"],
                         cwd=HERE, capture_output=True, text=True).returncode == 0
check("[E-448] the bus model compiles", osdi_ok)

if osdi_ok:
    reads = {}
    for bus in ("a", "c"):
        ladder = ("V1 in 0 dc 1\nRs in x 100\nRb b 0 1\n"
                  + "\n".join(f"R{k} x {bus}[{k}] 1k" for k in range(5)))
        ctl = ("pre_osdi constbus.osdi\nop\nprint "
               + " ".join(f"v({bus}[{k}])" for k in range(5)))
        rc, out = run(ladder + f"\nN1 {bus} b constbus", ctl, f"ab_{bus}",
                      cards=".option autobus\n.model constbus constbus r=1k")
        reads[bus] = [v for _, v in sorted(
            re.findall(r"v\(([^)]+)\)\s*=\s*(-?[\d.]+e[-+]\d+)", out, re.I))]
    check("[E-448] a bus named `a` reads all five bits (the reference)",
          len(reads["a"]) == 5, f"{reads['a']}")
    check("[E-448] a bus named `c` reads all five bits too",
          len(reads["c"]) == 5, f"{reads['c']}")
    check("[E-448] ...and they are BIT-IDENTICAL",
          reads["a"] == reads["c"] and len(reads["a"]) == 5)

rc, out = run(DIV_NC, "op\nlet z=vector(5)\nprint z[3]", "idx")
check("[E-448] ordinary vector indexing is untouched (control)",
      rc == 0 and near(last(out), 3.0), f"{last(out)}")
check("[E-448] ...and does not emit the ambiguity warning (control)",
      "is itself a vector" not in out)

# ------------------------------------------------------ numeric node names ---
print("\nnumeric node names are unaffected (controls)")
rc, out = run(NUM, "op\nprint v(2)", "num2")
check("[E-448] v(2) still reads node 2", rc == 0 and near(last(out), 0.5), f"{last(out)}")
rc, out = run(NUM, "op\nprint v(1)", "num1")
check("[E-448] v(1) still reads node 1", rc == 0 and near(last(out), 1.0), f"{last(out)}")

# ------------------------------------------------------- the bare-name case ---
print("\na bare name still resolves to the constant, but not in silence")
rc, out = run(DIV_C, "op\nsetplot new\nprint c", "bare_warn")
check("[E-448] bare `c` with the node in another plot warns",
      "resolved to the built-in constant" in out and near(last(out), 2.997925e8, 1e-4))
rc, out = run(DIV_C, "op\nprint c", "bare_node")
check("[E-448] ...but the ordinary read of that node is silent (control)",
      rc == 0 and near(last(out), 0.5) and "resolved to the built-in" not in out,
      f"{last(out)}")
rc, out = run(DIV_NC, "op\nprint c", "bare_const")
check("[E-448] ...and an ordinary constant read is silent (control)",
      rc == 0 and near(last(out), 2.997925e8, 1e-4) and "resolved to the built-in" not in out,
      f"{last(out)}")
rc, out = run(DIV_C, "op\nsetplot new\nprint pi", "bare_pi")
check("[E-448] ...and an unrelated constant stays silent (control)",
      rc == 0 and near(last(out), 3.14159265) and "resolved to the built-in" not in out,
      f"{last(out)}")

for f in os.listdir(HERE):
    if f.startswith("_cn_"):
        os.remove(os.path.join(HERE, f))

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
