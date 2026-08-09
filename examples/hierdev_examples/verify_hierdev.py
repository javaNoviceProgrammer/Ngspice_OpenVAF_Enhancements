#!/usr/bin/env python3
"""verify_hierdev.py -- Enhancement-410: `@x1.r1[param]` names the same device
as `@r.x1.r1[param]`.

(Not to be confused with hiername_examples, which is Enhancement-49 and concerns
hierarchical names INSIDE Verilog-A. This is ngspice's device accessor.)

WHY THE DEVICE-TYPE LETTER IS THERE AT ALL. ngspice flattens a subcircuit by
rewriting its cards back into the deck and re-parsing them as ordinary element
lines, and the parser takes the device type from the FIRST CHARACTER of the card
(inppas2.c: `c = *(current->line); switch (c)`). So the flattened refdes has to
keep a type letter in front -- `r1` inside `x1` becomes `r.x1.r1`, because the
card `x1.r1 a m 1k` would otherwise be re-read as another subcircuit call. Two
details confirm that is the reason rather than a guess:

  * translate_inst_name() (subckt.c) EXEMPTS `x` devices -- their name already
    begins with the right letter -- so `x2` inside `x1` is plain `x1.x2`;
  * NODES have no type, so they keep plain hierarchical paths: `x1.m`, `x1.x2.q`.

That asymmetry is the whole complaint: the node is `x1.m`, but the device beside
it is `r.x1.r1`. This restores the symmetry for the `@dev[param]` accessor.

NO SEARCH IS INVOLVED. The letter flattening prepends is literally the leaf
name's own first character, and ngspice already requires a device's name to begin
with its type letter -- so `x1.r1` can only ever mean `r.x1.r1`, and two device
types cannot share a leaf name.

STRICTLY A FALLBACK: every resolver looks the exact name up first, so nothing
that resolves today changes. Asserted below in both directions.

THE PRE-410 BEHAVIOUR WAS NOT ALWAYS AN ERROR: `sweep @x1.r1[resistance] 1k 3k 1k`
ran three points that were all IDENTICAL, because the knob never bound -- a
silent no-op sweep rather than a diagnostic. That case is pinned.

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
OSDI = os.path.join(tempfile.gettempdir(), "hierdev.osdi")

# r.x1.r1 = 1k, r.x1.x2.r1 = 2k, r.x1.x2.r2 = 3k, and the OSDI n.x1.x2.nd1 = 5k
DECK = """v1 a 0 dc 1
x1 a 0 outer
.subckt outer p n
r1 p m 1k
x2 m n inner
.ends
.subckt inner p n
r1 p q 2k
r2 q s 3k
nd1 s n mh
.ends
.model mh hierdev rval=5k"""


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(name, ctrl):
    path = os.path.join(tempfile.gettempdir(), f"hd_{name}.cir")
    with open(path, "w") as fh:
        fh.write(f"* hierdev {name}\n{DECK}\n.control\npre_osdi {OSDI}\n{ctrl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def last_val(out):
    m = re.findall(r"=\s*(-?[\d.]+e[+-]\d+)", out)
    return float(m[-1]) if m else None


def rows(out):
    return re.findall(r"^\s*\d+\s+(-?[\d.eE+-]+)", out, re.M)


def main():
    print("Enhancement-410: the device accessor without the device-type letter\n")
    r = subprocess.run([OPENVAF, os.path.join(HERE, "hierdev.va"), "-o", OSDI],
                       capture_output=True, text=True, timeout=600)
    if not check("hierdev.va compiles", r.returncode == 0 and os.path.exists(OSDI),
                 (r.stdout + r.stderr).strip().splitlines()[:1]):
        print(f"\n{passed}/{checks} checks passed")
        return 1

    print("\n  the two spellings name the same device")
    for full, short, want in [("@r.x1.r1", "@x1.r1", 1000.0),
                              ("@r.x1.x2.r1", "@x1.x2.r1", 2000.0),
                              ("@r.x1.x2.r2", "@x1.x2.r2", 3000.0)]:
        a = last_val(run("f" + short.strip("@").replace(".", "_"),
                         f"op\nprint {full}[resistance]"))
        b = last_val(run("s" + short.strip("@").replace(".", "_"),
                         f"op\nprint {short}[resistance]"))
        check(f"{full:14s} = {want:.0f}", a is not None and abs(a - want) < 1e-9, f"got {a}")
        check(f"{short:14s} = {want:.0f}  (new spelling)",
              b is not None and abs(b - want) < 1e-9, f"got {b}")
        check(f"{short} and {full} agree exactly", a is not None and a == b)

    print("\n  an OSDI device inside a subcircuit -- the `n` prefix, same rule")
    a = last_val(run("osdif", "op\nprint @n.x1.x2.nd1[rval]"))
    b = last_val(run("osdis", "op\nprint @x1.x2.nd1[rval]"))
    check("@n.x1.x2.nd1[rval] = 5000", a is not None and abs(a - 5000.0) < 1e-9, f"got {a}")
    check("@x1.x2.nd1[rval]   = 5000  (new spelling)",
          b is not None and abs(b - 5000.0) < 1e-9, f"got {b}")

    print("\n  every command that consumes the accessor, not just `print`")
    check("`let` accepts the short name",
          abs((last_val(run("let", "op\nlet z=@x1.x2.r2[resistance]\nprint z")) or 0)
              - 3000.0) < 1e-9)
    out = run("alter", "alter @x1.r1[resistance]=4k\nop\nprint @r.x1.r1[resistance]")
    check("`alter` writes through the short name (read back by the full one)",
          abs((last_val(out) or 0) - 4000.0) < 1e-9, f"got {last_val(out)}")
    out = run("alterosdi", "alter @x1.x2.nd1[rval]=7k\nop\nprint @n.x1.x2.nd1[rval]")
    check("`alter` works on the OSDI device too",
          abs((last_val(out) or 0) - 7000.0) < 1e-9, f"got {last_val(out)}")

    out = run("dcsweep", "dc @x1.r1[resistance] 1k 3k 1k\nprint i(v1)")
    got = rows(out)
    check("`dc` sweeps the short name -- 3 points, the knob really varying",
          len(got) == 3 and [float(g) for g in got] == [1000.0, 2000.0, 3000.0], str(got))

    # the silent case: pre-410 this ran 3 IDENTICAL points instead of failing
    out = run("sweep", "sweep @x1.r1[resistance] 1k 3k 1k -analysis op -output i1=i(v1)\n"
                       "print i1")
    got = [float(g) for g in rows(out)]
    want = [-1.0 / (rr + 10000.0) for rr in (1000.0, 2000.0, 3000.0)]  # +2k+3k+5k
    check("`sweep` binds the short name -- the current actually changes",
          len(got) == 3 and all(abs(g - w) <= 1e-6 * abs(w) for g, w in zip(got, want)),
          str(got))
    check("...and the three points are NOT identical (the pre-410 silent no-op)",
          len(set(got)) == 3, str(got))

    print("\n  `show`, whose query grammar could not express the spelling at all")
    # `show` takes the query's FIRST CHARACTER as the device-type selector
    # (`type = *word++`) and uses ':' / '#' -- not '.' -- as its subcircuit
    # delimiter, so `x1.r1` parsed as "type x" and could never match a resistor.
    # A whole-word alternative is consulted alongside that grammar, never
    # replacing it, so every legacy spelling below is unchanged.
    for q, want in [("r.x1.r1", "r.x1.r1"), ("x1.r1", "r.x1.r1"),
                    ("x1.x2.r1", "r.x1.x2.r1"), ("x1.x2.r2", "r.x1.x2.r2")]:
        out = run("show_" + q.replace(".", "_"), f"show {q} : resistance")
        check(f"show {q:12s} -> {want}", want in out and "No matching" not in out,
              [l.strip() for l in out.splitlines() if "No matching" in l][:1])
    # The legacy grammar, asserted on what it actually prints. (`:r1` means
    # "top-level r1", and this deck has none -- so "No matching" IS its correct
    # answer, and the whole-word alternative must not invent one.)
    for q, must in [("all : resistance", "r.x1.x2.r2"),
                    ("all : resistance", "3000"),
                    (":r1", "No matching"),
                    ("v1 : dc", "v1")]:
        out = run("legacy_" + re.sub(r"\W", "", q + must), f"op\nshow {q}")
        check(f"legacy `show {q}` still prints {must!r}", must in out)
    out = run("show_osdi", "show x1.x2.nd1 : rval")
    check("show x1.x2.nd1 -> the OSDI device", "n.x1.x2.nd1" in out)

    print("\n  backward compatibility, and what must still fail")
    check("a top-level device is unaffected",
          abs((last_val(run("top", "op\nprint @v1[dc]")) or -1) - 1.0) < 1e-9)
    out = run("bogus", "op\nprint @x1.nosuchdev[resistance]")
    check("a name matching nothing is still reported",
          "no such device" in out or "not available" in out)
    out = run("badparam", "op\nprint @x1.r1[nosuchparam]")
    check("a real device with a bogus parameter is still reported",
          "no such parameter" in out or "not available" in out)
    out = run("xleaf", "op\nprint @x1.x2[resistance]")
    check("an `x` leaf is given no phantom prefix",
          "no such device" in out or "not available" in out)
    out = run("plainnode", "op\nprint v(x1.m)")
    check("hierarchical NODES keep working (they never had a letter)",
          last_val(out) is not None)

    # ------------------------------------------------------------------
    # The same asymmetry, one level further in: a `.model` declared INSIDE a
    # subcircuit. subckt expansion renames it `<instance-path>:<model>` --
    # modtranslate() builds tprintf("%s:%s", scname, model_name) -- so a model in
    # x1 becomes `x1:rmod` and one in x1/x2 becomes `x1.x2:rmod`: levels joined by
    # '.', the model itself by ':'. Nothing else in the hierarchy is spelled that
    # way, so `@x1.rmod[res]` was answered "no such device or model name" and the
    # colon had to be discovered. The last '.' IS the instance-path/model
    # boundary at any depth, so the dotted spelling maps onto the real one.
    #
    # Same discipline as the device fallback above: tried only after the exact
    # instance and model lookups have failed, and skipped entirely for a name that
    # already contains ':'.
    print("\nA subcircuit-local .model written with a dot instead of its colon")

    MDECK = "\n".join([
        "v1 in 0 dc 1", "x1 in out outer", "r2 out 0 1k",
        ".subckt outer a b", "x2 a b inner", ".ends",
        ".subckt inner p q", "rx p q rmod", ".model rmod r (res=1000)", ".ends"])

    def mrun(name, ctrl):
        path = os.path.join(tempfile.gettempdir(), f"hd_mod_{name}.cir")
        with open(path, "w") as fh:
            fh.write(f"* hierdev model {name}\n{MDECK}\n.control\noption noacct\n"
                     f"{ctrl}\n.endc\n.end\n")
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=300)
        return r.stdout + r.stderr

    # v(out) = 1k / (res + 1k):  res=1000 -> 0.5, res=3000 -> 0.25
    out = mrun("dotted", "op\nprint @x1.x2.rmod[res]")
    check("[model] the dotted spelling resolves",
          last_val(out) == 1000.0, str(last_val(out)))
    out = mrun("colon", "op\nprint @x1.x2:rmod[res]")
    check("[model] ...to the same model as the real colon spelling",
          last_val(out) == 1000.0, str(last_val(out)))

    out = mrun("altermod", "op\naltermod @x1.x2.rmod[res]=3000\nop\nprint v(out)")
    check("[model] altermod drives it, and the circuit follows",
          last_val(out) is not None and abs(last_val(out) - 0.25) < 1e-9,
          str(last_val(out)))

    out = mrun("optimize", "optimize -mparam @x1.x2.rmod[res] 1000 100 10000 "
                           "-analysis op -target v(out) 0.25 -maxiter 40\n"
                           "print @x1.x2.rmod[res]")
    check("[model] optimize -mparam reaches it and finds res=3000",
          "converged" in out and last_val(out) == 3000.0,
          f"{last_val(out)} {out[-80:]}".replace("\n", " "))

    # and the boundaries: a name matching nothing must still fail, and E-410's
    # device resolution must not be shadowed by the new model fallback.
    out = mrun("nomodel", "op\nprint @x1.x2.nosuchmodel[res]")
    check("[model] a model name matching nothing is still reported",
          "no such device or model name" in out or "not available" in out)
    out = mrun("stilldev", "op\nprint @x1.x2.rx[resistance]")
    check("[model] a hierarchical DEVICE still resolves as a device",
          last_val(out) == 1000.0, str(last_val(out)))

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    sys.exit(main())
