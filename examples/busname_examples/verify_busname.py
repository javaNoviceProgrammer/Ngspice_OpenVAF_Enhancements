#!/usr/bin/env python3
"""verify_busname.py -- Enhancement-408: naming a bus node, and naming a
parameter whose own name contains brackets.

Three separate defects, all in the path between a name written in a deck and
the object it denotes:

  1. LEADING ZEROS.  `n[1]`, `n[01]` and `n[001]` were three DISTINCT nodes,
     while the vector lookup canonicalised the index -- so `print v(n[01])`
     silently returned `v(n[1])` and the node actually built as `n[01]` was
     unreachable by any spelling.  Bracket-specific: plain `n01`/`n1` were
     always distinct names and still are.

  2. A BRACKET INSIDE A PARAMETER NAME.  `show nd1 : all` lists the bus
     terminal currents `i_a[0]..i_a[3]` (Enhancement-394) and the array
     parameter elements `ap[0]..ap[2]` with correct values, and the instance
     line can SET `ap[0]=..`, but `@nd1[i_a[0]]` was truncated at the inner ']'
     and reported as "no such parameter i_a[0.".  Read failed, `alter` failed
     silently, and a `dc` sweep of it was a fatal error.

  3. A BUS RANGE ON AN OUTPUT OR IC CARD.  `a[0:3]` expanded on instance lines,
     R/C node lists, subcircuit calls and subcircuit port lists -- but not on
     `.save`/`.print`/`.plot` (the card produced nothing) or `.ic`/`.nodeset`
     (warned and ignored).

TRAP recorded because it cost a wrong conclusion: the Enhancement-269 wildcard
alias `@*[[param]]` DEPENDS on the old first-']' split leaving `[param`, so a
depth-tracking fix applied unconditionally silently changes it.  Every wildcard
form is asserted below for that reason.

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
OSDI = os.path.join(tempfile.gettempdir(), "busnames.osdi")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(name, body):
    path = os.path.join(tempfile.gettempdir(), f"bn_{name}.cir")
    with open(path, "w") as fh:
        fh.write(f"* busname {name}\n{body}\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=180)
    return r.stdout + r.stderr


def dev_deck(control):
    """The bus device, with every terminal driven at a distinct voltage."""
    return (f"v0 n[0] 0 dc 1\nv1 n[1] 0 dc 1\nv2 n[2] 0 dc 1\nv3 n[3] 0 dc 1\n"
            f"nd1 n[0:3] 0 mm\n.model mm busnames()\n"
            f".control\npre_osdi {OSDI}\n{control}\n.endc")


def val(out, expr):
    m = re.findall(re.escape(expr) + r"\s*=\s*(-?[\d.eE+-]+)", out)
    return float(m[0]) if m else None


def first_row(out):
    """{column name: value} for the first data row of a printed table.

    Read by NAME, not by position: a wide table paginates into column groups
    and repeats its header, so a fixed-offset regex silently picks up a '*'
    from the page break instead of a number."""
    lines = out.splitlines()
    got = {}
    for i, line in enumerate(lines):
        if not line.startswith("Index"):
            continue
        cols = line.split()[1:]
        for row in lines[i + 1:]:
            f = row.split()
            if len(f) == len(cols) + 1 and f[0] == "0":
                try:
                    got.update(zip(cols, (float(x) for x in f[1:])))
                except ValueError:
                    pass
                break
    return got


def main():
    print("Enhancement-408: bus node names, bracketed parameter names, bus ranges\n")
    r = subprocess.run([OPENVAF, os.path.join(HERE, "bus_names.va"), "-o", OSDI],
                       capture_output=True, text=True, timeout=600)
    if not check("bus_names.va compiles", r.returncode == 0 and os.path.exists(OSDI),
                 (r.stdout + r.stderr).strip().splitlines()[:1]):
        print(f"\n{passed}/{checks} checks passed")
        return 1

    # ---------------------------------------------------------------- finding 1
    print("\n1. a bracket index written with leading zeros names ONE node")
    out = run("canon", "v0 m[02] 0 dc 2\nr0 m[02] 0 1k\n"
                       ".control\nop\nprint v(m[2])\nprint v(m[02])\nprint v(m[002])\n"
                       "print v(m[0002])\n.endc")
    for spelling in ["v(m[2])", "v(m[02])", "v(m[002])", "v(m[0002])"]:
        got = val(out, spelling)
        check(f"{spelling:12s} = 2.0", got is not None and abs(got - 2.0) < 1e-9, f"got {got}")
    # the node built by the netlist must be the canonical one, not a fourth name
    out = run("canonall", "v0 m[02] 0 dc 2\nr0 m[02] 0 1k\n.control\nop\nprint all\n.endc")
    names = set(re.findall(r"m\[\d+\]", out))
    check("exactly one node exists, spelled canonically", names == {"m[2]"}, str(sorted(names)))

    # a NEGATIVE index still canonicalises, and plain names are untouched
    out = run("neg", "v0 m[-01] 0 dc 3\nr0 m[-01] 0 1k\n.control\nop\nprint v(m[-1])\n.endc")
    check("negative index canonicalises too", abs((val(out, "v(m[-1])") or 0) - 3.0) < 1e-9)
    out = run("plain", "v0 n01 0 dc 4\nv1 n1 0 dc 5\nr0 n01 0 1k\nr1 n1 0 1k\n"
                       ".control\nop\nprint v(n01)\nprint v(n1)\n.endc")
    check("UNBRACKETED n01 and n1 stay distinct names",
          abs((val(out, "v(n01)") or 0) - 4.0) < 1e-9
          and abs((val(out, "v(n1)") or 0) - 5.0) < 1e-9)

    # ---------------------------------------------------------------- finding 2
    print("\n2. `@dev[param]` can name a parameter whose own name has brackets")
    out = run("read", dev_deck("op\nprint @nd1[i_a[0]]\nprint @nd1[i_a[3]]\n"
                               "print @nd1[ap[0]]\nprint @nd1[ap[2]]\nprint @nd1[gs]"))
    for expr, want in [("@nd1[i_a[0]]", 1e-3), ("@nd1[i_a[3]]", 6e-3),
                       ("@nd1[ap[0]]", 1e-3), ("@nd1[ap[2]]", 3e-3), ("@nd1[gs]", 1e-3)]:
        got = val(out, expr)
        check(f"print {expr:14s} = {want}",
              got is not None and abs(got - want) <= 1e-9 + 1e-6 * abs(want), f"got {got}")

    out = run("let", dev_deck("op\nlet z=@nd1[i_a[0]]\nprint z"))
    check("`let` accepts it too", abs((val(out, "z") or 0) - 1e-3) < 1e-9)

    # a[3] carries 4e-3 + ap[0] + gs = 6 mA at 1 V; raising ap[0] to 5 mA gives 10 mA
    out = run("alter", dev_deck("alter @nd1[ap[0]]=5e-3\nop\nprint i(v3)"))
    check("`alter` writes it", abs((val(out, "i(v3)") or 0) + 1.0e-2) < 1e-9,
          f"i(v3)={val(out, 'i(v3)')}")
    out = run("sweep", dev_deck("dc @nd1[ap[0]] 1e-3 3e-3 1e-3\nprint i(v3)"))
    rows = re.findall(r"^\s*\d+\s+([\d.eE+-]+)\s+(-?[\d.eE+-]+)\s*$", out, re.M)
    want = [-6e-3, -7e-3, -8e-3]
    check("`dc` sweeps it -- 3 rows, i(v3) = -6, -7, -8 mA",
          len(rows) == 3 and all(abs(float(g) - w) < 1e-9 for (_, g), w in zip(rows, want)),
          str(rows))

    # a name that really is absent must still be reported, not silently accepted
    out = run("absent", dev_deck("op\nprint @nd1[nosuch[0]]"))
    check("an absent bracketed parameter is still reported",
          "no such parameter" in out or "syntax error" in out)

    print("\n   the Enhancement-268/269 wildcards, which rely on the OLD split")
    # `@*[[param]]` is Enhancement-269's instance alias, and it works ONLY
    # because the outer parse stops at the FIRST ']' and hands `[gs` on. Depth
    # tracking applied unconditionally would silently retarget it, so a name
    # that starts with '[' deliberately keeps the original split. These four
    # are the whole matrix, and each is pinned to its measured behaviour.
    for q, want_i, want_msg in [
            ("alter @#*[gs]=2e-3", -7e-3, None),                 # instance wildcard
            ("alter @*[[gs]]=2e-3", -7e-3, None),                # E-269 alias for it
            ("alter @*[gs]=2e-3", -6e-3, "use the instance wildcard"),
            ("alter @#*[[gs]]=2e-3", -6e-3, "no loaded instance has parameter '[gs'")]:
        out = run("w" + str(abs(hash(q)) % 9999), dev_deck(q + "\nop\nprint i(v3)"))
        got = val(out, "i(v3)")
        ok = got is not None and abs(got - want_i) < 1e-9
        if want_msg:
            ok = ok and want_msg in out
        check(f"`{q}` unchanged", ok, f"i(v3)={got}")

    # ---------------------------------------------------------------- finding 3
    print("\n3. a `[lo:hi]` bus range expands on output and IC cards")
    div = ("v1 in 0 dc 1\nr0 in a[0] 1k\nr1 in a[1] 2k\nr2 in a[2] 4k\nr3 in a[3] 8k\n"
           "rl0 a[0] 0 1k\nrl1 a[1] 0 1k\nrl2 a[2] 0 1k\nrl3 a[3] 0 1k\n")
    out = run("print", div + ".print dc v(a[0:3]) v(in)\n.dc v1 1 1 1")
    cols = re.findall(r"v\(a\[\d+\]\)", out)
    check(".print expands the range", sorted(set(cols)) == [f"v(a[{i}])" for i in range(4)],
          str(sorted(set(cols))))
    check(".print keeps the scalar probe beside it", "v(in)" in out)
    row = first_row(out)
    check("...and the four values are the four dividers",
          all(row.get(f"v(a[{i}])") is not None
              and abs(row[f"v(a[{i}])"] - w) < 1e-6
              for i, w in enumerate([0.5, 1 / 3, 0.2, 1 / 9])), str(row))

    out = run("save", div + ".save v(a[0:3])\n.dc v1 1 1 1\n.print dc v(a[0:3])")
    check(".save expands the range", "no data saved" not in out and "v(a[3])" in out)
    out = run("plot", div + ".plot dc v(a[0:3])\n.dc v1 1 1 1")
    check(".plot expands the range", "can't parse" not in out, )

    rc = "v1 in 0 dc 0\nr0 in a[0] 1k\nr1 in a[1] 1k\nc0 a[0] 0 1u\nc1 a[1] 0 1u\n"
    for lab, card in [(".ic  v(a[0:1])=0.25", ".ic v(a[0:1])=0.25"),
                      (".ic  v(a[0:1]) = 0.25", ".ic v(a[0:1]) = 0.25"),
                      (".nodeset v(a[0:1])=0.25", ".nodeset v(a[0:1])=0.25")]:
        out = run("ic" + str(abs(hash(lab)) % 9999),
                  rc + card + "\n.tran 1u 2u uic\n.print tran v(a[0:1])")
        row = first_row(out)
        ok = (len(row) == 3 and all(abs(row[f"v(a[{i}])"] - 0.25) < 1e-3 for i in (0, 1))
              and "non-existent node" not in out)
        check(f"{lab:24s} applies to every element", ok, str(row))

    # a two-range token has no unambiguous expansion and is deliberately left alone
    out = run("two", div + ".print dc v(a[0:1],a[2:3])\n.dc v1 1 1 1")
    check("a token naming TWO ranges is left literal and still reported",
          "can't parse" in out)

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    sys.exit(main())
