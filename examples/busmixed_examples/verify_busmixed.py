#!/usr/bin/env python3
"""Enhancement-490: an instance line that MIXES the two ways of writing a bus port.

`.option autobus` (Enhancement-444) lets one token stand for a whole bus port,
and it fires on a token count equal to the PORT count. Positional binding covers
the other complete form, a count equal to the TERMINAL count. A line that writes
one port in shorthand and another port's bits out in full is NEITHER:

    N1 a b[0:2] bmix          for  inout [0:4] a;  inout [0:2] b;

so it used to fall through both and bind POSITIONALLY against the flat terminal
list -- `a` onto a[0], then `b[0]` onto a[1], `b[1]` onto a[2]. Every node one or
more terminals off. Measured on a model whose bits each carry a different
conductance:

    N1 a b[0:4] bmix      node b[0] saw the conductance of terminal a[1]
                          (2 V through 1/2 rather than 1/32)

The only thing said was Enhancement-402's warning about the terminals left over
at the tail, which names the symptom and not the cause: a user who supplies the
two nodes it asks for still has a circuit wired entirely wrong. Enhancement-445's
own diagnostic -- "already carries an index, so it cannot be expanded as the bus
port" -- exists for exactly this mistake but sits inside the count check, so it
could never reach the line that needed it.

THE FIX. Nothing here is ambiguous. Walk the ports left to right and let each
token say which form it is in: a bare name on a bus port is shorthand for that
port's bits; a token already carrying an index -- or ground, which E-445
established can never be indexed -- means the port was written out, so take one
token per bit. The rewrite is accepted only when the walk consumes exactly the
tokens the line has. Anything else means the bits written do not match the width
the model declares, which no reading can repair: refuse it there, where the port
and both counts are still in hand to say so, rather than let the old silent
misbinding through.

Every positive check is a differential against the same circuit written out in
full, on a device where all eight bits read differently.
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
        if junk.startswith("_bx_"):
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


def run(body, tag, ctl, opts=".option autobus\n"):
    deck = (f"mixed bus port forms {tag}\n{opts}{body}\n"
            ".model bmix bmix\n.model bscal bscal\n.model bdesc bdesc\n"
            f".control\npre_osdi busmixed.osdi\noption noacct\nset numdgt=8\n{ctl}\n"
            ".endc\n.end\n")
    p = os.path.join(HERE, f"_bx_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=120, errors="replace")
    return r.returncode, r.stdout + r.stderr


def cur(out):
    """every printed branch current, in order"""
    return [v for _n, v in re.findall(
        r"i\((v\d+)\)\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?)", out, re.I)]


ABITS = [f"a[{k}]" for k in range(5)]
BBITS = [f"b[{k}]" for k in range(3)]
ALL = ABITS + BBITS


def drive(nodes):
    return "\n".join(f"V{i} {n} 0 dc 2" for i, n in enumerate(nodes))


def prints(n):
    return "op\n" + "\n".join(f"print i(V{i})" for i in range(n))


r = subprocess.run([OPENVAF, "busmixed.va", "-o", "busmixed.osdi"], cwd=HERE,
                   capture_output=True, text=True)
print("Enhancement-490: mixing shorthand and written-out bus bits\n")
check("[E-490] the Verilog-A models compile",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "busmixed.osdi")),
      (r.stdout + r.stderr).strip()[:60])

# ------------------------------------------------ the reference: all explicit
REF = drive(ALL) + "\nN1 " + " ".join(ALL) + " bmix"
rc_r, out_r = run(REF, "ref", prints(8))
ref = cur(out_r)
check("[E-490] the all-explicit reference runs", rc_r == 0 and len(ref) == 8, f"{ref}")
check("[E-490] ...on a device where all eight bits differ", len(set(ref)) == 8, "")

# ------------------------------------------------------- the defect ---------
print("\nmixed forms that add up must now bind exactly like the explicit line")
for label, inst in [
        ("shorthand `a` + explicit range `b[0:2]`", "N1 a b[0:2] bmix"),
        ("explicit range `a[0:4]` + shorthand `b`", "N1 a[0:4] b bmix"),
        ("shorthand `a` + bits written one by one", "N1 a b[0] b[1] b[2] bmix"),
        ("bits written one by one + shorthand `b`", "N1 " + " ".join(ABITS) + " b bmix"),
]:
    rc, out = run(drive(ALL) + "\n" + inst, "m" + str(abs(hash(inst)) % 99999), prints(8))
    got = cur(out)
    check(f"[E-490] {label}", rc == 0 and got == ref, f"{got[:3]}...")
    check("[E-490] ...and no terminal is reported unconnected",
          "not connected" not in out and "absent" not in out, "")

print("\na bus tied off with explicit grounds, the other in shorthand")
rc_g, out_g = run(drive(ABITS) + "\nN1 a 0 0 0 bmix", "gnd", prints(5))
rc_x, out_x = run(drive(ABITS) + "\nN1 " + " ".join(ABITS) + " 0 0 0 bmix", "gndx", prints(5))
check("[E-490] `N1 a 0 0 0` reads as shorthand + three grounds",
      rc_g == 0 and cur(out_g) == cur(out_x) and len(cur(out_g)) == 5, f"{cur(out_g)}")
check("[E-490] ...with nothing left unconnected", "not connected" not in out_g, "")

print("\na SCALAR port beside a bus on a mixed line takes one token")
SC = drive(ABITS) + "\nVs s 0 dc 0\nN1 " + " ".join(ABITS) + " s bscal"
rc_s1, out_s1 = run(SC, "sc1", prints(5))
rc_s2, out_s2 = run(drive(ABITS) + "\nVs s 0 dc 0\nN1 a s bscal", "sc2", prints(5))
check("[E-490] the scalar port is not expanded",
      rc_s2 == 0 and cur(out_s2) == cur(out_s1) and len(cur(out_s1)) == 5,
      f"{cur(out_s2)}")

print("\nbits come from the model's own indices, mixed form included")
PB = [f"p[{k}]" for k in range(5)]
QB = [f"q[{k}]" for k in range(1, 4)]
rc_d1, out_d1 = run(drive(PB + QB) + "\nN1 " + " ".join(PB + QB) + " bdesc", "d1", prints(8))
rc_d2, out_d2 = run(drive(PB + QB) + "\nN1 p " + " ".join(QB) + " bdesc", "d2", prints(8))
check("[E-490] a `[4:0]` port keeps its indices in the mixed form",
      rc_d2 == 0 and cur(out_d2) == cur(out_d1) and len(cur(out_d1)) == 8,
      f"{cur(out_d2)[:3]}...")
rc_d3, out_d3 = run(drive(PB + QB) + "\nN1 " + " ".join(PB) + " q bdesc", "d3", prints(8))
check("[E-490] ...and so does a `[1:3]` port", rc_d3 == 0 and cur(out_d3) == cur(out_d1),
      f"{cur(out_d3)[5:]}")

print("\nthe same under `.option autobus=kicad` (E-462)")
AK = [f"a_{k}_" for k in range(5)]
BK = [f"b_{k}_" for k in range(3)]
rc_k1, out_k1 = run(drive(AK + BK) + "\nN1 " + " ".join(AK + BK) + " bmix", "k1",
                    prints(8), opts=".option autobus=kicad\n")
rc_k2, out_k2 = run(drive(AK + BK) + "\nN1 a " + " ".join(BK) + " bmix", "k2",
                    prints(8), opts=".option autobus=kicad\n")
check("[E-490] a KiCad-spelled bit is recognised as written-out",
      rc_k2 == 0 and cur(out_k2) == cur(out_k1) == ref, f"{cur(out_k2)[:3]}...")
rc_k3, out_k3 = run(drive(AK + BK) + "\nN1 a b_0_ b_1_ bmix", "k3", "op",
                    opts=".option autobus=kicad\n")
check("[E-490] ...and a short KiCad-spelled line is refused, not misbound",
      rc_k3 != 0 and "do not add up" in out_k3, "")

# ------------------------------------------------------ what must be refused
print("\nmixed forms that do NOT add up are refused, naming the cause")
rc_e1, out_e1 = run(drive(["a"]) + "\nN1 a b[0:4] bmix", "e1", "op")
check("[E-490] a range wider than the port it feeds is refused", rc_e1 != 0, "")
check("[E-490] ...the message says the two forms do not add up",
      "mixes a bus port written in shorthand" in out_e1 and "do not add up" in out_e1, "")
check("[E-490] ...it names the PORT, not one of its terminals",
      "'a' in shorthand" in out_e1 and "'a[0]' in shorthand" not in out_e1, "")
check("[E-490] ...and gives both counts that would work",
      "2 tokens (each bus in shorthand)" in out_e1 and "or 8 (every bit" in out_e1, "")
check("[E-490] ...and nothing is simulated on a misbound circuit",
      "not connected" not in out_e1, "")

rc_e2, out_e2 = run(drive(["a"]) + "\nN1 a b[0] b[1] bmix", "e2", "op")
check("[E-490] too few written-out bits is refused too", rc_e2 != 0, "")
check("[E-490] ...saying the reading runs out",
      "runs out before every port is fed" in out_e2, "")

# ------------------------------------------------- what must not change -----
print("\nwhat the fix must leave alone")
rc_a, out_a = run(drive(ALL) + "\nN1 a b bmix", "allshort", prints(8))
check("[E-490] an all-shorthand line is unchanged", rc_a == 0 and cur(out_a) == ref,
      f"{cur(out_a)[:3]}...")
check("[E-490] an all-explicit line is unchanged", ref == cur(out_r), "")

rc_p, out_p = run(drive(["q"]) + "\nN1 a[0] b bmix", "e445a", "op")
check("[E-490] E-445 still refuses an indexed token where a port is expected",
      "already carries an index" in out_p, "")
check("[E-490] ...and now names the port 'a', not the terminal 'a[0]'",
      "bus port 'a'" in out_p and "bus port 'a[0]'" not in out_p, "")
rc_z, out_z = run(drive(["q"]) + "\nN1 0 b bmix", "e445b", "op")
check("[E-490] E-445 still refuses ground as a bus token",
      "ground cannot be indexed" in out_z and "bus port 'a'" in out_z, "")

rc_u, out_u = run(drive(["a[0]"]) + "\nN1 a[0] a[1] a[2] bmix", "under", "op")
check("[E-490] a short line with NO shorthand still gets E-402's warning",
      "not connected" in out_u and "do not add up" not in out_u, "")

rc_o, out_o = run(drive(["a"]) + "\nN1 a b[0:2] bmix", "off", "op", opts="")
check("[E-490] with autobus OFF a mixed line is left exactly as it was",
      rc_o == 0 and "not connected" in out_o and "do not add up" not in out_o, "")

print("\n`.option autobus=1` is an on-word, not an unknown style")
rc_1, out_1 = run(drive(ALL) + "\nN1 a b bmix", "one", prints(8),
                  opts=".option autobus=1\n")
check("[E-490] `autobus=1` turns the option on", rc_1 == 0 and cur(out_1) == ref, "")
check("[E-490] ...without reporting a style that does not exist",
      "unknown autobus style" not in out_1, "")
rc_b, out_b = run(drive(ALL) + "\nN1 a b bmix", "bogus", prints(8),
                  opts=".option autobus=bogus\n")
check("[E-490] a genuinely unknown style is still reported",
      "unknown autobus style 'bogus'" in out_b, "")
for word in ("true", "yes", "on"):
    rc_w, out_w = run(drive(ALL) + "\nN1 a b bmix", "w" + word, prints(8),
                      opts=f".option autobus={word}\n")
    check(f"[E-490] `autobus={word}` still works and stays quiet",
          rc_w == 0 and cur(out_w) == ref and "unknown autobus style" not in out_w, "")
for word in ("0", "false", "no", "off"):
    rc_w, out_w = run(drive(ALL) + "\nN1 a b bmix", "f" + word, "op",
                      opts=f".option autobus={word}\n")
    check(f"[E-490] `autobus={word}` still switches it off",
          "not connected" in out_w, "")

print("\na mixed line whose buses are both LOCAL to a subcircuit")
# E-464 expands a mixed line at FLATTENING time only when a bus FORMAL is
# involved; with both buses local it leaves the line for INP2N, which is where
# this fix now reads it. The bits must come out as x1.a[k] -- the same node a
# hand-written `a[0]` inside the subcircuit translates to.
LADDER = ("\n".join(f"Rn{k} n a[{k}] 1k" for k in range(5)) + "\n"
          + "\n".join(f"Rm{k} n b[{k}] 1k" for k in range(3)))
PROBE = "op\n" + "\n".join(f"print v(x1.{n})" for n in ALL)


def sub(form, tag):
    body = ("V0 n 0 dc 2\nX1 n s\n.subckt s n\n" + LADDER + "\n"
            + form + "\n.ends")
    return run(body, tag, PROBE)


def volts(out):
    return [v for _n, v in re.findall(
        r"v\(([^)]+)\)\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?)", out, re.I)]


rc_v1, out_v1 = sub("N1 " + " ".join(ALL) + " bmix", "sub_exp")
rc_v2, out_v2 = sub("N1 a b[0:2] bmix", "sub_mix")
ref_v = volts(out_v1)
check("[E-490] the all-explicit subcircuit reference runs",
      rc_v1 == 0 and len(ref_v) == 8 and len(set(ref_v)) == 8, f"{ref_v[:3]}...")
check("[E-490] a local mixed line expands to the same x1.a[k] nodes",
      rc_v2 == 0 and volts(out_v2) == ref_v, f"{volts(out_v2)[:3]}...")
check("[E-490] ...with nothing left unconnected",
      "not connected" not in out_v2 and "absent" not in out_v2, "")
rc_v3, out_v3 = sub("N1 a b bmix", "sub_short")
check("[E-490] and the all-shorthand subcircuit line still matches",
      rc_v3 == 0 and volts(out_v3) == ref_v, f"{volts(out_v3)[:3]}...")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
