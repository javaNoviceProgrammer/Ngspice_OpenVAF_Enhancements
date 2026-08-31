#!/usr/bin/env python3
"""The four instance knobs an OSDI device shares with every built-in: `m`,
`temp`, `dtemp` and `dt`.

These are the parameters ngspice supplies *itself* on top of whatever the model
declares, and each has a routing rule that is easy to get wrong from either
side. [Enhancement-394](../../enhancements_doc/Enhancement-394.md) fixed two of
them (the subcircuit multiplier never reached an OSDI device; instance `temp=`
was used as Kelvin without converting from Celsius), and
[Enhancement-396](../../enhancements_doc/Enhancement-396.md) had to *withdraw* a
finding about a third after misreading it. This suite exists so none of that has
to be re-derived.

WHAT IT PINS

  [1] `m` reaches an OSDI device exactly as it reaches a built-in -- at device
      level, through a subcircuit, compounded across nesting levels, and in AC
      and transient as well as DC. Every check carries a built-in resistor in
      the same topology, because "the OSDI number changed" is not evidence;
      "the OSDI number equals what the equivalent built-in network gives" is.

  [2] `m` and `$mfactor` are DISTINCT PARAMETERS, not two views of one.
      OpenVAF always emits `$mfactor` (netlist name `_mfactor`, from the `$`->`_`
      rewrite in osdiinit.c); ngspice normally registers an extra alias keyword
      `m` pointing at it. `osdiregistry.c` sets `has_m` when the model declares
      its own instance parameter named `m`, and then that alias is simply not
      registered -- so the model's parameter takes the netlist KEYWORD, while
      `$mfactor` keeps its default and stays reachable as `_mfactor`.

      The consequence is that the two MULTIPLY. `m=3 _mfactor=2` is 6x on a model
      that owns `m`; on one that does not they are one slot (aliasparam), and
      setting both on one line is refused per LRM 3.4.7.

  [3] A model that declares one of these names OWNS IT. ngspice hands over the
      netlist value and applies nothing of its own, for `m`, `temp`, `dtemp` and
      `dt` alike. A model that declares `m` and USES it scales correctly and
      leaves `$mfactor` at 1 -- there is no double application in either
      direction. A model that declares `m` and IGNORES it loses the multiplier,
      which is the model's bug and is pinned here so that "fixing" it by
      double-applying would fail this suite.

      This is exactly the case that produced a wrong finding in E-396: a probe
      that declared `m` without using it looked like "the subcircuit multiplier
      is silently defeated". A real compact model declares `m` and scales by it,
      which is what `has_m` exists for.

  [4] Temperature arrives correctly by every route -- `.temp`, `.option temp`,
      instance `temp=` (converted from Celsius), instance `dtemp=`/`dt=` (both
      spellings), and the combinations -- verified against a BUILT-IN RESISTOR
      USED AS A THERMOMETER: R(T) = R0*(1 + tc1*(T - Tnom)) is solved back for T
      from the measured current, giving an independent reading of what the
      simulator handed the device.

      `temp=` overrides `dtemp=` and says so, as every built-in does.

  [5] `$vt` tracks `$temperature` exactly. The check is a RATIO test rather than
      an absolute one on purpose: `constants.vams` and ngspice's own CONSTboltz/
      CHARGE are different CODATA vintages, so `$vt` differs from a textbook
      k*T/q by a few ppm. That difference is real and is not a defect, and an
      absolute comparison would either fail spuriously or need a tolerance loose
      enough to hide a genuine error.

  [7] READ-BACK. ngspice's own `temp`/`dtemp`/`dt` entries were registered
      `IF_SET` without `IF_ASK`, so a value could be written and never read:
      `@n1[temp]` answered "no such parameter" where every built-in reports one,
      `show` listed neither, and a `sweep` over them ended with a spurious error
      AFTER completing correctly. Enhancement-397 serves them from `OSDIask`,
      matching the built-in convention exactly -- `temp` in DEGREES CELSIUS
      defaulting to the ambient and NOT including dtemp, `dtemp`/`dt` the offset
      defaulting to zero -- and forces `dtemp` to 0 when `temp` overrides it, as
      `restemp.c` does, so what is reported is what is used.

      The synthesized ids had to move above Enhancement-394's terminal-current
      range first: `dt`'s id WAS terminal 0's id, survivable only while the two
      were disjoint by direction. The terminal currents are re-pinned here for
      that reason.

  [6] `.temp` propagates into subcircuits and through nesting, and a subcircuit
      parameter forwarded to the device (`.subckt s p n dtemp=0` / `N1 p n mm
      dtemp={dtemp}`) works. `temp=` written directly on an `X` line is NOT
      supported -- but it is equally unsupported for a built-in device, because
      an `X` line binds SUBCIRCUIT parameters, not device parameters. That is
      core ngspice semantics and the suite pins the two behaving alike rather
      than asserting one is a bug.
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
HDR = '`include "disciplines.vams"\n`include "constants.vams"\n'
KELVIN = 273.15


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


# A 1 mS conductance that reports every quantity the four knobs can touch.
# `decl` optionally gives the model its own instance parameter; `scale` is the
# factor the model applies itself.
def source(decl="", scale="", own="-1.0"):
    return HDR + f"""module dut(p,n);
 inout p,n; electrical p,n;
 {decl}
 (* desc="mfact" *) real mfact;
 (* desc="ownm"  *) real ownm;
 (* desc="tdev"  *) real tdev;
 (* desc="vt"    *) real vt;
 (* desc="teff"  *) real teff;
 analog begin
   mfact = $mfactor;
   ownm  = {own};
   tdev  = $temperature;
   vt    = $vt;
   teff  = $temperature + {'dtemp' if 'dtemp' in decl else '0.0'};
   I(p,n) <+ {scale} V(p,n)*1e-3;
 end
endmodule
"""


VARIANTS = {
    "plain":        source(),
    "own_m_used":   source('(*type="instance"*) parameter real m = 1.0;', "m*", "m"),
    "own_m_unused": source('(*type="instance"*) parameter real m = 1.0;', "", "m"),
    "own_m_int":    source('(*type="instance"*) parameter integer m = 1;', "m*", "m"),
    "own_temp":     source('(*type="instance"*) parameter real temp = 27.0;'),
    "own_dtemp":    source('(*type="instance"*) parameter real dtemp = 0.0;'),
    "own_dt":       source('(*type="instance"*) parameter real dt = 0.0;'),
}
BUILT = {}


def build_src(src, tag):
    d = os.path.join(HERE, "_op_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def build(tag):
    if tag in BUILT:
        return BUILT[tag]
    d = os.path.join(HERE, "_op_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(VARIANTS[tag])
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    BUILT[tag] = (d, r.returncode, (r.stdout or "") + (r.stderr or ""))
    return BUILT[tag]


def run(d, deck, guard=40):
    open(os.path.join(d, "q.cir"), "w").write(deck)
    r = subprocess.run(["perl", "-e", f"alarm {guard}; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def num(out, pat):
    m = re.search(pat, out, re.M)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def osdi(d, net, cards="", body="op\nprint i(v1)", path="n1",
         opvars=("mfact", "ownm", "tdev", "vt", "teff"), src="V1 a 0 dc 1 ac 1"):
    pv = " ".join(f"@{path}[{v}]" for v in opvars)
    deck = ("t\n.control\npre_osdi m.osdi\n.endc\n" + src + "\n" + net + "\n" + cards +
            "\n.control\noption noacct\nset numdgt=12\n" + body + " " + pv + "\n.endc\n.end\n")
    rc, out = run(d, deck)
    res = {"rc": rc, "i": num(out, r"^i\(v1\)\s*=\s*(\S+)"), "out": out}
    for v in opvars:
        res[v] = num(out, rf"@\S*\[{v}\]\s*=\s*(\S+)")
    return res


def builtin_current(d, net, cards=""):
    """the same topology with a 1k resistor in place of the OSDI device"""
    deck = ("t\n" + cards + "\nV1 a 0 dc 1\n" + net +
            "\n.control\noption noacct\nset numdgt=12\nop\nprint i(v1)\n.endc\n.end\n")
    rc, out = run(d, deck)
    return num(out, r"^i\(v1\)\s*=\s*(\S+)")


def builtin_thermometer(d, rline, cards=""):
    """R(T) = R0*(1 + tc1*(T-Tnom)); solve back for T from the measured current"""
    tc1, r0, tnom = 0.01, 1000.0, 27.0
    i = builtin_current(d, rline, cards)
    if i is None or i == 0:
        return None
    return (1.0 / abs(i) / r0 - 1.0) / tc1 + tnom + KELVIN


SUBCKTS = """
.subckt s p n
N1 p n mm
.ends
.subckt s3 p n
N1 p n mm m=3
.ends
.subckt t2 p n
X2 p n s m=3
.ends
.subckt u3 p n
X3 p n s m=5
.ends
.subckt u2 p n
X2 p n u3 m=3
.ends
"""
RSUBS = """
.subckt sr p n
R1 p n 1k
.ends
.subckt sr3 p n
R1 p n 1k m=3
.ends
.subckt tr2 p n
XR2 p n sr m=3
.ends
.subckt ur3 p n
XR3 p n sr m=5
.ends
.subckt ur2 p n
XR2 p n ur3 m=3
.ends
"""
MODEL = "\n.model mm dut()\n"


def close(a, b, rel=1e-9):
    return a is not None and b is not None and abs(a - b) <= rel * max(1e-12, abs(b))


def main():
    for tag in VARIANTS:
        d, rc, out = build(tag)
        check(f"the '{tag}' probe model compiles", rc == 0,
              (out.strip().splitlines() or [""])[0][:60])

    d = build("plain")[0]

    # ---------------------------------------------------------------- [1] m
    print("\n  -- [1] `m` reaches an OSDI device like it reaches a built-in --")
    MCASES = [
        ("device, no m",           "N1 a 0 mm",        "R1 a 0 1k",        "n1", 1.0),
        ("device m=3",             "N1 a 0 mm m=3",    "R1 a 0 1k m=3",    "n1", 3.0),
        ("device m=0.5",           "N1 a 0 mm m=0.5",  "R1 a 0 1k m=0.5",  "n1", 0.5),
        ("device m=2.5",           "N1 a 0 mm m=2.5",  "R1 a 0 1k m=2.5",  "n1", 2.5),
        ("device m=0",             "N1 a 0 mm m=0",    "R1 a 0 1k m=0",    "n1", 0.0),
        ("device m=1000",          "N1 a 0 mm m=1000", "R1 a 0 1k m=1000", "n1", 1000.0),
        ("subckt X (no m)",        "X1 a 0 s",         "XR1 a 0 sr",       "n.x1.n1", 1.0),
        ("subckt X m=3",           "X1 a 0 s m=3",     "XR1 a 0 sr m=3",   "n.x1.n1", 3.0),
        ("subckt m=2 x device m=3", "X1 a 0 s3 m=2",   "XR1 a 0 sr3 m=2",  "n.x1.n1", 6.0),
        ("nested X 2 x 3",         "X1 a 0 t2 m=2",    "XR1 a 0 tr2 m=2",  "n.x1.x2.n1", 6.0),
        ("nested X 2 x 3 x 5",     "X1 a 0 u2 m=2",    "XR1 a 0 ur2 m=2",  "n.x1.x2.x3.n1", 30.0),
    ]
    for label, onet, bnet, path, mult in MCASES:
        r = osdi(d, onet, cards=MODEL + SUBCKTS, path=path)
        b = builtin_current(d, bnet, RSUBS)
        want = -1e-3 * mult
        check(f"{label}: current is {mult:g}x and equals the built-in network",
              close(r["i"], want) and close(r["i"], b), f"osdi={r['i']} builtin={b}")
        check(f"{label}: $mfactor reads {mult:g}", close(r["mfact"], mult),
              f"{r['mfact']}")

    for label, body, pat in [("AC", "ac lin 1 1k 1k\nprint mag(i(v1))", r"mag\(i\(v1\)\)\s*=\s*(\S+)"),
                             ("transient", "tran 1u 3u\nlet z=i(v1)\nprint z[2]", r"z\[2\]\s*=\s*(\S+)")]:
        for mult in (1, 3, 7):
            suffix = "" if mult == 1 else f" m={mult}"
            rc, out = run(d, ("t\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1 ac 1\n"
                              f"N1 a 0 mm{suffix}\n" + MODEL +
                              "\n.control\noption noacct\nset numdgt=12\n" + body + "\n.endc\n.end\n"))
            v = num(out, pat)
            check(f"m={mult} scales in {label} too, not only DC",
                  v is not None and abs(abs(v) - 1e-3 * mult) <= 1e-6 * 1e-3 * mult, f"{v}")

    # -------------------------------------------------- [2] m vs $mfactor
    print("\n  -- [2] `m` and `$mfactor` are distinct parameters --")
    dp = build("plain")[0]
    du = build("own_m_used")[0]
    for tag, dd, cases in [
        ("plain model: `m` is an ALIAS of $mfactor (one slot)", dp,
         [("m=3", "N1 a 0 mm m=3", 3.0), ("_mfactor=2", "N1 a 0 mm _mfactor=2", 2.0)]),
        ("model owns `m`: the two are independent and MULTIPLY", du,
         [("m=3", "N1 a 0 mm m=3", 3.0), ("_mfactor=2", "N1 a 0 mm _mfactor=2", 2.0),
          ("m=3 _mfactor=2 -> 6x", "N1 a 0 mm m=3 _mfactor=2", 6.0)]),
    ]:
        print(f"     {tag}")
        for label, net, mult in cases:
            r = osdi(dd, net, cards=MODEL)
            check(f"  {label}", close(r["i"], -1e-3 * mult),
                  f"i={r['i']} $mfactor={r['mfact']} own_m={r['ownm']}")

    # On a plain model `m` and `_mfactor` are one slot (aliasparam), and LRM
    # 3.4.7 makes setting both on one line an ERROR -- the run refuses instead
    # of the old "last write wins" warning.
    r = osdi(dp, "N1 a 0 mm m=3 _mfactor=2", cards=MODEL)
    check("writing `m` and `_mfactor` on one line is refused (LRM 3.4.7)",
          r["i"] is None and any("same parameter" in ln for ln in r["out"].splitlines()),
          [ln.strip()[:56] for ln in r["out"].splitlines() if "same parameter" in ln][:1])

    # ------------------------------------------- [3] a model that owns `m`
    print("\n  -- [3] a model that declares one of these names owns it --")
    for tag, mult, note in [("own_m_used", 3.0, "declares and USES m"),
                            ("own_m_unused", 1.0, "declares and IGNORES m (model's bug)")]:
        dd = build(tag)[0]
        r = osdi(dd, "X1 a 0 s m=3", cards=MODEL + SUBCKTS, path="n.x1.n1")
        check(f"{note}: X1 m=3 gives {mult:g}x", close(r["i"], -1e-3 * mult),
              f"i={r['i']} $mfactor={r['mfact']} own_m={r['ownm']}")
        check(f"{note}: $mfactor stays 1 (ngspice applies nothing)",
              close(r["mfact"], 1.0), f"{r['mfact']}")

    di = build("own_m_int")[0]
    for label, net, mult in [("integer m=3", "N1 a 0 mm m=3", 3.0),
                             ("integer m=2.5 rounds to 3", "N1 a 0 mm m=2.5", 3.0)]:
        r = osdi(di, net, cards=MODEL)
        check(f"an integer `m`: {label}", close(r["i"], -1e-3 * mult), f"i={r['i']}")
    r = osdi(dp, "N1 a 0 mm m=2.5", cards=MODEL)
    check("a plain model takes m=2.5 as 2.5x exactly (it is real)",
          close(r["i"], -2.5e-3), f"i={r['i']}")

    # ------------------------------------------------ [4] temp/dtemp/dt
    print("\n  -- [4] temperature by every route, against a built-in thermometer --")
    TCASES = [
        ("default 27 C",          "",                "N1 a 0 mm",                  "R1 a 0 1k tc1=0.01",                    300.15),
        (".temp 75",              ".temp 75",        "N1 a 0 mm",                  "R1 a 0 1k tc1=0.01",                    348.15),
        (".option temp=75",       ".option temp=75", "N1 a 0 mm",                  "R1 a 0 1k tc1=0.01",                    348.15),
        ("instance temp=75",      "",                "N1 a 0 mm temp=75",          "R1 a 0 1k tc1=0.01 temp=75",            348.15),
        ("instance temp=-40",     "",                "N1 a 0 mm temp=-40",         "R1 a 0 1k tc1=0.01 temp=-40",           233.15),
        ("instance temp=0",       "",                "N1 a 0 mm temp=0",           "R1 a 0 1k tc1=0.01 temp=0",             273.15),
        ("instance dtemp=10",     "",                "N1 a 0 mm dtemp=10",         "R1 a 0 1k tc1=0.01 dtemp=10",           310.15),
        ("instance dt=10",        "",                "N1 a 0 mm dt=10",            "R1 a 0 1k tc1=0.01 dtemp=10",           310.15),
        (".temp 75 + dtemp=10",   ".temp 75",        "N1 a 0 mm dtemp=10",         "R1 a 0 1k tc1=0.01 dtemp=10",           358.15),
        ("temp=75 AND dtemp=10",  "",                "N1 a 0 mm temp=75 dtemp=10", "R1 a 0 1k tc1=0.01 temp=75 dtemp=10",   348.15),
    ]
    for label, cards, onet, bline, wantT in TCASES:
        r = osdi(d, onet, cards=MODEL + "\n" + cards)
        b = builtin_thermometer(d, bline, cards)
        check(f"{label}: $temperature is {wantT} K",
              close(r["tdev"], wantT, 1e-12), f"{r['tdev']}")
        check(f"{label}: the built-in device sees the same temperature",
              b is not None and abs(b - wantT) < 1e-3, f"builtin={b}")

    check("`temp=` overrides `dtemp=` and says so",
          any("dtemp ignored" in ln for ln in
              osdi(d, "N1 a 0 mm temp=75 dtemp=10", cards=MODEL)["out"].splitlines()),
          "")

    # E-394: temp=0 must not make $vt zero (it used to divide by zero)
    r = osdi(d, "N1 a 0 mm temp=0", cards=MODEL)
    check("temp=0 gives a usable $vt, not zero (E-394)",
          r["vt"] is not None and r["vt"] > 0.02, f"vt={r['vt']}")

    # ------------------------------------------------------- [5] $vt vs T
    print("\n  -- [5] $vt tracks $temperature (ratio test, vintage-independent) --")
    ref = None
    for cards in ("", ".temp 75", ".temp -40", ".temp 127"):
        r = osdi(d, "N1 a 0 mm", cards=MODEL + "\n" + cards)
        if ref is None:
            ref = (r["tdev"], r["vt"])
            continue
        check(f"$vt/$vt0 == T/T0 at {r['tdev']} K",
              close(r["vt"] / ref[1], r["tdev"] / ref[0], 1e-12),
              f"vt ratio={r['vt']/ref[1]:.12f} T ratio={r['tdev']/ref[0]:.12f}")

    # ------------------------------------------------- [6] subcircuits
    print("\n  -- [6] temperature and subcircuits --")
    SUBT = MODEL + "\n.subckt s p n\nN1 p n mm\n.ends\n.subckt t2 p n\nX2 p n s\n.ends\n"
    for label, net, cards, path, want in [
        ("`.temp 75` reaches a device inside a subckt", "X1 a 0 s", ".temp 75", "n.x1.n1", 348.15),
        ("`.temp 75` reaches a nested subckt", "X1 a 0 t2", ".temp 75", "n.x1.x2.n1", 348.15),
    ]:
        r = osdi(d, net, cards=SUBT + "\n" + cards, path=path)
        check(label, close(r["tdev"], want, 1e-12), f"{r['tdev']}")

    FWD = MODEL + "\n.subckt s p n dtemp=0\nN1 p n mm dtemp={dtemp}\n.ends\n"
    for dt, want in [(0, 300.15), (10, 310.15), (50, 350.15)]:
        net = "X1 a 0 s" + ("" if dt == 0 else f" dtemp={dt}")
        r = osdi(d, net, cards=FWD, path="n.x1.n1")
        check(f"a subckt parameter forwarded to the device: dtemp={dt}",
              close(r["tdev"], want, 1e-12), f"{r['tdev']}")

    # `temp=` on an X line is core ngspice semantics, not an OSDI shortcoming
    ro = osdi(d, "X1 a 0 s temp=75", cards=SUBT)
    rb = builtin_current(d, "XR1 a 0 sr temp=75", "\n.subckt sr p n\nR1 p n 1k tc1=0.01\n.ends\n")
    check("`temp=` on an X line fails for OSDI and built-in alike (X binds subckt params)",
          ro["i"] is None and rb is None, f"osdi={ro['i']} builtin={rb}")

    # ------------------------- a model that declares AND applies its own dtemp
    print("\n  -- a model that declares one of these names applies it itself --")
    for tag, inst, want_dev, want_eff in [
        ("own_dtemp", "N1 a 0 mm dtemp=10", 300.15, 310.15),
        ("own_dtemp", "N1 a 0 mm dt=10", 300.15, 310.15),
    ]:
        dd = build(tag)[0]
        r = osdi(dd, inst, cards=MODEL)
        check(f"{tag} + `{inst.split('mm ')[1]}`: ngspice leaves $temperature alone",
              close(r["tdev"], want_dev, 1e-12), f"{r['tdev']}")
        check(f"{tag} + `{inst.split('mm ')[1]}`: the model's own offset gives {want_eff} K",
              close(r["teff"], want_eff, 1e-12), f"{r['teff']}")

    for tag in ("own_temp", "own_dt"):
        dd = build(tag)[0]
        r = osdi(dd, "N1 a 0 mm", cards=MODEL)
        check(f"{tag}: the model owning the name still simulates",
              r["rc"] == 0 and close(r["i"], -1e-3), f"i={r['i']}")

    # ============================================ [7] read-back (E-397)
    print("\n  -- [7] reading the knobs back, against the built-in convention --")
    READBACK = [
        ("nothing set",         "",         "",                   27.0, 0.0),
        ("temp=75",             "",         " temp=75",           75.0, 0.0),
        ("dtemp=10",            "",         " dtemp=10",          27.0, 10.0),
        ("dt=10",               "",         " dt=10",             27.0, 10.0),
        (".temp 85",            ".temp 85", "",                   85.0, 0.0),
        (".temp 85 + dtemp=10", ".temp 85", " dtemp=10",          85.0, 10.0),
        ("temp=75 dtemp=10",    "",         " temp=75 dtemp=10",  75.0, 0.0),
    ]
    for label, cards, extra, wt, wd in READBACK:
        r = osdi(d, "N1 a 0 mm" + extra, cards=MODEL + "\n" + cards,
                 opvars=("temp", "dtemp", "dt"))
        check(f"{label}: @n1[temp] reads {wt:g} degC", close(r["temp"], wt), f"{r['temp']}")
        check(f"{label}: @n1[dtemp] reads {wd:g}", close(r["dtemp"], wd), f"{r['dtemp']}")
        check(f"{label}: @n1[dt] agrees with @n1[dtemp]", close(r["dt"], wd), f"{r['dt']}")
        bo = run(d, ("t\n" + cards + "\nV1 a 0 dc 1\nR1 a 0 1k tc1=0.01"
                     + extra.replace(" dt=10", " dtemp=10") + "\n"
                     ".control\noption noacct\nset numdgt=12\nop\n"
                     "print @r1[temp] @r1[dtemp]\n.endc\n.end\n"))[1]
        bt = num(bo, r"@r1\[temp\]\s*=\s*(\S+)")
        bd = num(bo, r"@r1\[dtemp\]\s*=\s*(\S+)")
        check(f"{label}: the built-in reports the same temp/dtemp",
              close(r["temp"], bt) and close(r["dtemp"], bd),
              f"osdi=({r['temp']},{r['dtemp']}) builtin=({bt},{bd})")

    # the physics must not have moved
    for label, extra, wantT in [
            ("temp=75 dtemp=10 still means 348.15 K", " temp=75 dtemp=10", 348.15),
            ("dtemp=10 alone still means 310.15 K", " dtemp=10", 310.15)]:
        r = osdi(d, "N1 a 0 mm" + extra, cards=MODEL, opvars=("tdev",))
        check(label, close(r["tdev"], wantT, 1e-12), f"{r['tdev']}")

    rc2, o = run(d, ("t\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1\nN1 a 0 mm\n"
                     + MODEL + ".control\noption noacct\nop\nshow n1\n.endc\n.end\n"))
    listed = [k for k in ("m", "temp", "dtemp", "dt") if re.search(rf"^\s*{k}\s", o, re.M)]
    check("`show` lists m, temp, dtemp and dt", len(listed) == 4, ",".join(listed))

    for knob, spec, npts in [("@n1[temp]", "0 100 25", 5), ("@n1[dtemp]", "0 40 10", 5),
                             ("@n1[dt]", "0 40 10", 5), ("@n1[m]", "1 4 1", 4)]:
        rc2, o = run(d, ("t\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1\nN1 a 0 mm\n"
                         + MODEL + ".control\noption noacct\nset numdgt=12\n"
                         f"sweep {knob} {spec} -analysis op -output oo=@n1[tdev]\n"
                         "setplot sweep1\nprint oo\n.endc\n.end\n"), guard=60)
        rows = re.findall(r"^\s*\d+\s+([-+0-9.eE]+)\s*$", o, re.M)
        bad = [ln.strip() for ln in o.splitlines() if ln.startswith(("Error", "Warning"))]
        check(f"sweep {knob} yields {npts} points with no spurious diagnostic",
              len(rows) == npts and not bad, f"{len(rows)} pts; {bad[:1]}")

    # E-394's terminal currents must survive the id move that made this possible
    TRI = HDR + """module dut3(a,b,c);
 inout a,b,c; electrical a,b,c;
 analog begin I(a,b) <+ V(a,b)*1e-3; I(b,c) <+ V(b,c)*2e-3; end
endmodule
"""
    d3, rc3, out3 = build_src(TRI, "tri")
    check("the three-terminal probe compiles", rc3 == 0, out3.strip().splitlines()[:1])
    if rc3 == 0:
        rc2, o = run(d3, ("t\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1\nVb b 0 dc 0.5\n"
                          "N1 a b 0 mm\n.model mm dut3()\n"
                          ".control\noption noacct\nset numdgt=12\nop\n"
                          "print @n1[i_a] @n1[i_b] @n1[i_c] @n1[temp]\n.endc\n.end\n"))
        cur3 = [num(o, rf"@n1\[i_{t}\]\s*=\s*(\S+)") for t in "abc"]
        check("E-394 terminal currents still resolve after the id move",
              all(c is not None for c in cur3), f"{cur3}")
        check("and still satisfy KCL",
              all(c is not None for c in cur3) and abs(sum(cur3)) < 1e-12,
              f"sum={sum(c or 0 for c in cur3)}")
        check("while @n1[temp] on the same device reads the ambient",
              close(num(o, r"@n1\[temp\]\s*=\s*(\S+)"), 27.0), "")

    rc2, o = run(d, ("t\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1\nN1 a 0 mm dtemp=10\n"
                     + MODEL + ".control\noption noacct\nset numdgt=12\nop\n"
                     "print @n1[i] @n1[i_p] @n1[i_n]\n.endc\n.end\n"))
    ip = num(o, r"@n1\[i_p\]\s*=\s*(\S+)")
    inn = num(o, r"@n1\[i_n\]\s*=\s*(\S+)")
    check("the two-terminal bare `i` alias still resolves",
          num(o, r"@n1\[i\]\s*=\s*(\S+)") is not None and close(ip, -inn), f"i_p={ip} i_n={inn}")

    dd = build("own_dtemp")[0]
    r = osdi(dd, "N1 a 0 mm dtemp=25", cards=MODEL, opvars=("dtemp", "tdev"))
    check("a model-declared `dtemp` is still read from the model's own parameter",
          close(r["dtemp"], 25.0) and close(r["tdev"], 300.15, 1e-12),
          f"dtemp={r['dtemp']} tdev={r['tdev']}")

    for j in os.listdir(HERE):
        if j.startswith("_op_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    return 0 if passed == checks else 1


sys.exit(main())
