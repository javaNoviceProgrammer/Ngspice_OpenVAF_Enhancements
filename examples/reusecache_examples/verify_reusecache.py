#!/usr/bin/env python3
"""
verify_reusecache.py -- `.option osdicache` and `.option reusesetup`, the dig of
2026-09-07, end-to-end through the committed openvaf-r + ngspice on both solvers.

`.option osdicache` (E-500) lets `pre_osdi -va` skip a source whose object is
already up to date. Found and fixed (Enhancement-573):
  1. an edit to a file the source `include`s did not count -- the cache loaded
     the object of the previous text; the staleness test now walks the includes
  2. a compiler newer than the object was loaded anyway -- the very hazard E-500
     gave for making the cache opt-in; the object must now be newer than openvaf-r
  3. two sources with the same stem in different directories compiled onto ONE
     object: the second overwrote the first while loaded, was reported "already
     loaded" and never registered; a source with a directory now names its object
     after the directory too (a/m.va -> osdi/a_m.osdi)
  4. `noosdicache` was reported an unknown option; it is now the off spelling
The spellings that always worked (`=0`, `= 0`, `=off`) are pinned alongside.

`.option reusesetup` (E-471) keeps the circuit standing between sweep points and
runs CKTtemp instead of a setup. Two device quantities were computed at SETUP only
and went stale on every path that changes a parameter without one -- the reused
sweep, `alter`, the `.dc` of E-533/E-534 that a single-knob op sweep becomes:
  5. the resistor's flicker-noise area (l, w, lf, wf, short, narrow): a noise
     sweep over @r1[l] rose where a standalone run falls
  6. the BJT's SPICE2 c2/c4 form -- an `ise` above 1e-4 is a multiplier of `is`
     -- was folded into the parameter in place, so a swept `is` kept the leakage
     of the FIRST `is`, with the setup reused or rebuilt alike
Both are now recomputed at temperature time from the values as they stand.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def ngspice(path, compiler=OPENVAF):
    # the compiler reaches pre_osdi through the OPENVAF environment variable: a
    # `set openvaf=` in the deck's control block runs AFTER the pre_ commands
    r = subprocess.run([NGSPICE, "-b", path], cwd=HERE, capture_output=True,
                       text=True, timeout=300, env=dict(os.environ, OPENVAF=compiler))
    return r.stdout + r.stderr


def deck(tag, body, opt=""):
    """A deck in its own work directory (so its osdi/ is its own); returns its path."""
    d = os.path.join(HERE, "_w_" + tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "a")); os.makedirs(os.path.join(d, "b"))
    for f in ("rmod.va", "inc.va", "body.inc"):
        shutil.copy(os.path.join(HERE, f), d)
    for sub in ("a", "b"):
        shutil.copy(os.path.join(HERE, sub, "m.va"), os.path.join(d, sub))
    now = time.time() - 10                          # sources older than any object built now
    for f in ("rmod.va", "inc.va", "body.inc", "a/m.va", "b/m.va"):
        os.utime(os.path.join(d, f), (now, now))
    with open(os.path.join(d, "t.cir"), "w") as fh:
        fh.write(f"reusecache {tag}\n{opt}{body}")
    return os.path.join("_w_" + tag, "t.cir")


def values(out, names):
    vals = {}
    for line in out.splitlines():
        s = line.strip()
        for n in names:
            if s.lower().startswith(n.lower() + " "):
                try:
                    vals[n] = float(s.split("=", 1)[1].split()[0])
                except (ValueError, IndexError):
                    pass
    return vals


def column(out):
    """the values of a `print sweep1.y` table"""
    return [float(m.group(1)) for m in re.finditer(r"^\d+\s+(-?[\d.]+e[-+]\d+)", out, re.M)]


def run_deck(title, body):
    p = os.path.join(HERE, "_o.cir")
    with open(p, "w") as fh:
        fh.write(f"{title}\n{body}")
    return ngspice("_o.cir")


def near(a, b, rel=1e-9):
    return a is not None and b is not None and abs(a - b) <= rel * max(abs(a), abs(b), 1e-300)


ONE_R = ("v1 1 0 1\nn1 1 0 dm\n.model dm rmod\n"
         ".control\npre_osdi -va rmod.va\n.endc\n.control\nop\nprint i(v1)\n.endc\n.end\n")

RN = ("v1 1 0 dc 1 ac 1\nr1 1 o rmod w=1u l=%s\nr2 o 0 1k\n"
      ".model rmod r rsh=1000 kf=1e-10 af=1 ef=1 lf=1 wf=1 short=0 narrow=0\n")
NOISE = "noise v(o) v1 dec 2 1k 10k"

BJ = "vcc c 0 5\nvb b 0 0.7\nq1 c b 0 qm\n.model qm npn is=%s ise=%s bf=100 ne=1.5\n"


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] .option osdicache: the spellings")
    for spell, cached in (("osdicache", True), ("osdicache=0", False), ("osdicache = 0", False),
                          ("osdicache=off", False), ("noosdicache", False)):
        p = deck("sp", ONE_R, opt=f".option {spell}\n")
        ngspice(p)
        out = ngspice(p)
        check(f"`.option {spell}`: the second run {'skips' if cached else 'recompiles'}",
              ("is up to date" in out) == cached and "unknown option" not in out
              and near(values(out, ["i(v1)"]).get("i(v1)"), -1e-3),
              "up to date" if "is up to date" in out else "rebuilt")

    print("[2] an edit to an INCLUDED file invalidates the cache")
    body = ("v1 1 0 1\nn1 1 0 dm\n.model dm rinc\n.control\npre_osdi -va inc.va\n.endc\n"
            ".control\nop\nprint i(v1)\n.endc\n.end\n")
    p = deck("inc", body, opt=".option osdicache\n")
    out1 = ngspice(p)
    out2 = ngspice(p)
    check("inc.va and its body.inc: built once, then up to date",
          "inc.va -> " in out1 and "is up to date" in out2, "")
    inc = os.path.join(HERE, "_w_inc", "body.inc")
    with open(inc) as fh:
        s = fh.read()
    with open(inc, "w") as fh:
        fh.write(s.replace("1000.0", "2000.0"))
    t = time.time() + 2
    os.utime(inc, (t, t))                               # newer than the object
    out3 = ngspice(p)
    check("body.inc edited (inc.va untouched): the object is rebuilt and the answer follows, -1m -> -0.5m",
          "is up to date" not in out3 and near(values(out3, ["i(v1)"]).get("i(v1)"), -0.5e-3),
          f"{values(out3, ['i(v1)'])}")

    print("[3] a compiler newer than the object rebuilds it")
    ovf = os.path.join(HERE, "_w_cmp", "ovf")
    p = deck("cmp", ONE_R, opt=".option osdicache\n")
    shutil.copy(OPENVAF, ovf); os.chmod(ovf, 0o755)
    ngspice(p, compiler=ovf)
    t = time.time() + 2
    os.utime(ovf, (t, t))
    out = ngspice(p, compiler=ovf)
    check("the compiler touched after the object: `is older than the compiler ...; rebuilding`",
          "older than the compiler" in out and "rmod.va -> " in out
          and near(values(out, ["i(v1)"]).get("i(v1)"), -1e-3), "")
    t = time.time() - 100
    os.utime(ovf, (t, t))
    out = ngspice(p, compiler=ovf)
    check("...and with the compiler older again the object is up to date",
          "is up to date" in out, "")
    # Enhancement-574: the compiler named by BARE NAME on PATH -- the lookup's
    # last resort -- is located there and checked the same way; before, a
    # bare name could not be stat'ed and the rule was silently inert, so the
    # same deck cached or rebuilt depending on how the compiler had been named
    pathdir = os.path.join(HERE, "_w_cmp", "onpath")
    os.makedirs(pathdir, exist_ok=True)
    shutil.copy(OPENVAF, os.path.join(pathdir, "openvaf-r")); os.chmod(os.path.join(pathdir, "openvaf-r"), 0o755)
    env = dict(os.environ, PATH=pathdir + os.pathsep + os.environ.get("PATH", ""))
    env.pop("OPENVAF", None)
    r = subprocess.run([NGSPICE, "-b", p], cwd=HERE, capture_output=True, text=True, timeout=300, env=env)
    t = time.time() + 2
    os.utime(os.path.join(pathdir, "openvaf-r"), (t, t))
    r = subprocess.run([NGSPICE, "-b", p], cwd=HERE, capture_output=True, text=True, timeout=300, env=env)
    out = r.stdout + r.stderr
    check("a compiler found by bare name on PATH is located and checked too: `older than the compiler .../onpath/openvaf-r`",
          "older than the compiler" in out and "onpath/openvaf-r" in out and "rmod.va -> " in out,
          "" if "onpath/openvaf-r" in out else out.strip().splitlines()[-1][:80] if out.strip() else "")

    print("[4] two sources with the same stem in different directories")
    body = ("v1 1 0 1\nn1 1 0 dma\nn2 1 0 dmb\n.model dma ra\n.model dmb rb\n"
            ".control\npre_osdi -va a/m.va b/m.va\n.endc\n.control\nop\nprint i(v1)\n.endc\n.end\n")
    p = deck("stem", body)
    out = ngspice(p)
    check("a/m.va and b/m.va both load: i(v1) = -1.5 mA (1k || 2k)",
          near(values(out, ["i(v1)"]).get("i(v1)"), -1.5e-3) and "already loaded" not in out,
          f"{values(out, ['i(v1)'])}")
    check("their objects are osdi/a_m.osdi and osdi/b_m.osdi",
          os.path.isfile(os.path.join(HERE, "_w_stem", "osdi", "a_m.osdi"))
          and os.path.isfile(os.path.join(HERE, "_w_stem", "osdi", "b_m.osdi")), "")
    p = deck("stemc", body, opt=".option osdicache\n")
    ngspice(p)
    out = ngspice(p)
    check("under the cache both are up to date on the second run",
          out.count("is up to date") == 2 and near(values(out, ["i(v1)"]).get("i(v1)"), -1.5e-3), "")
    p = deck("bare", ONE_R)
    ngspice(p)
    check("a bare rmod.va still lands in osdi/rmod.osdi",
          os.path.isfile(os.path.join(HERE, "_w_bare", "osdi", "rmod.osdi")), "")

    print("[5] reusesetup: a resistor's flicker-noise area follows its geometry")
    standalone = []
    for l in ("1u", "2u", "4u"):
        out = run_deck("standalone", RN % l + f".control\nset numdgt=10\n{NOISE}\nprint onoise_total\n.endc\n.end\n")
        standalone.append(values(out, ["onoise_total"]).get("onoise_total"))
    check("standalone runs: the total output noise falls with l",
          all(v is not None for v in standalone) and standalone[0] > standalone[1] > standalone[2],
          f"{standalone}")
    out = run_deck("reuse", RN % "1u" + ".control\nset numdgt=10\nset ngdebug\n"
                   f"sweep @r1[l] list 1u 2u 4u -analysis {NOISE} -output y=onoise_total\nprint sweep1.y\n.endc\n.end\n")
    swept = column(out)
    m = re.search(r"setup reused at (\d+) of 3 points", out)
    check("a `sweep @r1[l]` with the setup reused matches the standalone runs at every point",
          len(swept) == 3 and all(near(a, b, 1e-7) for a, b in zip(swept, standalone)),
          f"{swept}")
    check("...and the setup WAS reused (2 of 3 points), so this is the fast path",
          m is not None and m.group(1) == "2", m.group(0) if m else "no tally")
    out = run_deck("alter", RN % "1u" + f".control\nset numdgt=10\n{NOISE}\nalter @r1[l]=4u\n{NOISE}\nprint noise4.onoise_total\n.endc\n.end\n")
    check("an `alter @r1[l]` followed by a noise analysis matches the standalone run too",
          near(values(out, ["noise4.onoise_total"]).get("noise4.onoise_total"), standalone[2], 1e-7),
          f"{values(out, ['noise4.onoise_total'])}")

    print("[6] reusesetup: a BJT `ise` given as a multiplier of `is`")
    ref = {}
    for is_ in ("1e-15", "1e-14"):
        out = run_deck("standalone", BJ % (is_, "2") + ".control\nset numdgt=10\nop\nprint i(vb)\n.endc\n.end\n")
        ref[is_] = values(out, ["i(vb)"]).get("i(vb)")
    check("standalone: ise=2 (> 1e-4, the c2 form) scales with is -- the base current grows ~10x",
          ref["1e-15"] is not None and ref["1e-14"] is not None
          and 8 < ref["1e-14"] / ref["1e-15"] < 12, f"{ref}")
    sw = "sweep @qm[is] list 1e-15 1e-14 -analysis op -output y=i(vb)\nprint sweep1.y\n"
    for how, ctl in (("as one .dc (E-533)", sw), ("per point, setup reused", sw.replace("-analysis op", "-perpoint -analysis op")),
                     ("per point, setup rebuilt", "set reusesetup=0\n" + sw.replace("-analysis op", "-perpoint -analysis op"))):
        out = run_deck("bjt", BJ % ("1e-15", "2") + f".control\nset numdgt=10\n{ctl}.endc\n.end\n")
        col = column(out)
        check(f"a sweep of @qm[is] {how} matches both standalone points",
              len(col) == 2 and near(col[0], ref["1e-15"], 1e-7) and near(col[1], ref["1e-14"], 1e-7),
              f"{col}")
    out = run_deck("ask", BJ % ("1e-15", "2") + ".control\nop\nprint @qm[ise]\n.endc\n.end\n")
    check("`@qm[ise]` reads back the value as given (2), not the resolved product",
          near(values(out, ["@qm[ise]"]).get("@qm[ise]"), 2.0), f"{values(out, ['@qm[ise]'])}")
    out = run_deck("plain", BJ % ("1e-14", "1e-16") + ".control\nset numdgt=10\nop\nprint i(vb)\n.endc\n.end\n")
    plain = values(out, ["i(vb)"]).get("i(vb)")
    out = run_deck("plain", BJ % ("1e-15", "1e-16") + ".control\nset numdgt=10\nsweep @qm[is] list 1e-15 1e-14 -perpoint -analysis op -output y=i(vb)\nprint sweep1.y\n.endc\n.end\n")
    col = column(out)
    check("an ordinary ise (below 1e-4) is unchanged: the swept point equals the standalone run",
          plain is not None and len(col) == 2 and near(col[1], plain, 1e-7), f"{col} vs {plain}")

    print("[7] reusesetup: an initial condition with uic is applied at every point")
    body = "v1 1 0 1\nr1 1 2 1k\nc1 2 0 1u\n.ic v(2)=0.5\n"
    res = {}
    for reuse in ("1", "0"):
        out = run_deck("ic", body + f".option reusesetup={reuse}\n.control\nset numdgt=10\n"
                       "sweep @r1[r] list 1k 2k 4k -analysis tran 1u 100u uic -output y=v(2)[0]\nprint sweep1.y\n.endc\n.end\n")
        res[reuse] = column(out)
    check("v(2) at t=0 is the .ic value at all three points, with the reuse on and off alike",
          len(res["1"]) == 3 and res["1"] == res["0"] and all(abs(v - 0.5) < 1e-3 for v in res["1"]),
          f"{res['1']}")

    for d in os.listdir(HERE):
        if d.startswith("_w_"):
            shutil.rmtree(os.path.join(HERE, d), ignore_errors=True)
    print("\nALL PASSED" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
