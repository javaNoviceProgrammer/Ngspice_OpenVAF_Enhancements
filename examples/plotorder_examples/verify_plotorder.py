#!/usr/bin/env python3
"""Enhancement-383: adding a plot-type entry is not enough -- it has to go in the
right PLACE, and four of them did not.

`ft_plotabbrev()` returns the FIRST entry in plotabs[] whose pattern is a
SUBSTRING of the plot's name. [E-367](../../enhancements_doc/Enhancement-367.md)
registered the plot types this project added, and [E-368](../../enhancements_doc/Enhancement-368.md)
did the same for the periodic analyses -- both by ADDING entries, and both wrote
the ordering rule into the source:

    ORDER MATTERS: a more specific pattern must precede one that is a
    substring of it.

E-367 then broke that rule with its own entry. `envelope` was added at the BOTTOM
of the table, below { "op", "op" }, and "envel-OP-e" contains "op" -- so the entry
could never be reached and envelope plots were named op1:

    Current op1   Envelope Following Analysis (Envelope Following)

`setplot envelope1` therefore failed, and the plot collided with the numbering of
real operating-point plots. Auditing every name in the tree that reaches
plot_alloc() against the table turned up three more of the same shape:

    envelope -> op1     collides with operating-point plots  (E-367's own entry, dead)
    qpac     -> pac1    collides with .pac                   (no entry existed)
    qpxf     -> pxf1    collides with .pxf                   (no entry existed)
    spectrum -> sp1     collides with .sp (S-parameters)     (entry existed, dead)

The `spectrum` one is pre-existing upstream behaviour, and E-367's source comment
had recorded it as an unfixable quirk. It is not unfixable -- `{ "spect", "spect" }`
was already sitting in the table, unreachable, for exactly this purpose. It now
precedes the `sp` entries, so `spec` produces spect1 rather than a second sp<N>
that nothing can tell apart from an S-parameter plot. THAT IS A USER-VISIBLE
CHANGE to a vanilla ngspice command, and it is deliberate.

WHERE `spect` HAD TO GO is the interesting constraint, and check [12] below is
what guards it: the noise analysis names its plot

    "Noise SPECTral Density Curves - (V^2 or A^2)/Hz"

which contains "spect". Moving the entry too far up would have renamed every
ordinary noise plot to spect<N> -- turning a naming fix into a naming regression
in decks all over this repo that do `setplot noise1`. It sits BELOW
{ "noise", "noise" } and above the `sp` entries.

ONE CANDIDATE WAS DELIBERATELY NOT FIXED. `vectors.c`'s findvec_alle() calls
plot_alloc("digi"), which has no table entry and falls through to "unknown" --
apparently the same defect. It is not: the very next line overwrites the result
with a hardcoded `pl_typename = copy("dig1")`, so an entry would be dead on
arrival. That path was also unreachable from every invocation tried here
(`print alle`, `plot alle`, with event nodes confirmed present via `eprint`), so
adding an entry would have meant shipping an untested, unreachable entry -- which
is the exact defect this enhancement removes. It is left alone.

CHECK [17] IS THE ONE THAT KEEPS THIS FIXED. Each of the four defects above was a
single misplaced line that no runtime test existed to catch, and two of them were
introduced BY the enhancements that were fixing this same table. So the invariant
itself is asserted against the source: for every plot name in the tree that
reaches plot_alloc(), no EARLIER pattern may be a substring of it. A future entry
added in the wrong place fails that check without anyone having to think of a deck
that would expose it.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


# A driven RC low-pass: enough for envelope, spec, noise, ac, tran and op.
RC = """V1 in 0 DC 0 AC 1 SIN(0 1 1meg)
R1 in out 1k
C1 out 0 1n
"""
# The periodic analyses need a real nonlinearity to have harmonics to convert.
# A plain junction diode is enough -- no OSDI model, so this example has no
# OpenVAF dependency and stays fast.
MIX = """V1 x 0 SIN(0 1 1meg) AC 1
V2 a x SIN(0 0.2 3.1meg)
R1 a b 1k
D1 b 0 dm
.model dm d(is=1e-14 cjo=1p)
"""
# a 2-port for the S-parameter control. The SIN() on the port-1 source is there
# so the same deck can also run a transient and a `spec` -- `sp` itself only uses
# the AC specification, so it is unaffected.
SP = """V1 in 0 dc 0 ac 1 portnum 1 z0 50 SIN(0 1 1meg)
V2 out 0 dc 0 ac 0 portnum 2 z0 50
R1 in out 1k
C1 out 0 1n
"""
# `spec <fstart> <fstop> <fstep> <vec>` cannot resolve finer than 1/tstop, and
# asking it to emits no plot at all -- which reads exactly like a naming failure.
# tstop = 2 us, so the step must be >= 500 kHz.
SPEC = "tran 5n 2u\nspec 0 5e6 5e5 v(out)"


def run(net, cards, ctl, tag, timeout=600):
    p = os.path.join(HERE, "_po_%s.cir" % tag)
    with open(p, "w") as f:
        f.write("plot ordering\n" + net + cards +
                ".control\noption noacct\n" + ctl + "\nsetplot\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return ""
    return r.stdout + r.stderr


def plots(out):
    """Parse the LAST `setplot` listing. A blank line follows the header, so a
    non-greedy match to the first blank line captures nothing -- the trap
    E-368's harness hit, which made it report 'no plot' for every analysis and
    call the run clean."""
    i = out.rfind("List of plots available:")
    if i < 0:
        return []
    names = []
    for line in out[i:].splitlines()[1:]:
        if "\t" not in line:
            if names:
                break
            continue
        m = re.match(r"\s*(?:Current\s+)?(\S+)\t", line)
        if m and m.group(1) != "const":
            names.append(m.group(1))
    return names


def current(out):
    """The plot `setplot` reports as current, from the LAST listing."""
    i = out.rfind("List of plots available:")
    m = re.search(r"^Current\s+(\S+)\t", out[i:], re.M) if i >= 0 else None
    return m.group(1) if m else None


def pre(names, p):
    """Plots whose abbreviation is exactly `p` followed by digits."""
    return [n for n in names if re.fullmatch(re.escape(p) + r"\d+", n)]


def brief(names, n=8):
    """`sweep` keeps a plot per point, so a 3-point sweep lists 300-odd op<N>
    plots (E-367 explains why the numbers run that high). Show the head."""
    return " ".join(names[:n]) + ("" if len(names) <= n
                                  else " ... (+%d more)" % (len(names) - n))


# (label, net, cards, control, wanted abbrev, the abbrev it used to steal)
DEFECTS = [
    ("envelope", RC,  "", "envelope out 1meg 20u",            "envelope", "op"),
    ("qpac",     MIX, "", "qpss v(b) 1meg 3.1meg hb 4 1\n"
                          "qpac lin 3 100k 300k",             "qpac",     "pac"),
    ("qpxf",     MIX, "", "qpss v(b) 1meg 3.1meg hb 4 1\n"
                          "qpxf b lin 3 100k 300k",           "qpxf",     "pxf"),
    ("spec",     RC,  "", SPEC,                               "spect",    "sp"),
    # `fft` is the OTHER producer of a "Spectrum" plot (com_fft.c and spec.c both
    # set pl_name to that literal), so it was named sp<N> for the same reason and
    # is fixed by the same line. It is listed separately because it is a different
    # command reaching the same defect, and because E-345's example asserts this
    # exact name -- that expectation was updated with this change, not around it.
    ("fft",      RC,  "", "tran 5n 2u\nlinearize\nfft v(out)", "spect",   "sp"),
]

# Must hold on BOTH binaries: these are the names decks all over this repo
# already select, and a fix that moved them would be worse than the defect.
REGRESSIONS = [
    ("ordinary op keeps op<N>",        RC,  "", "op",                          "op"),
    ("ordinary tran keeps tran<N>",    RC,  "", "tran 50n 2u",                 "tran"),
    ("ordinary ac keeps ac<N>",        RC,  "", "ac dec 3 1e4 1e8",            "ac"),
    ("ordinary noise keeps noise<N>",  RC,  "", "noise v(out) V1 dec 3 1e4 1e6", "noise"),
    ("s-parameters keep sp<N>",        SP,  "", "sp lin 3 1e6 1e8",            "sp"),
    (".pac keeps pac<N>",              RC,
     ".pac 1meg 1u out 1024 10 50 5u dec 4 10k 1meg\n", "run",                 "pac"),
    (".pxf keeps pxf<N>",              RC,
     ".pxf 1meg 1u out 1024 10 50 5u out dec 4 10k 1meg 1\n", "run",           "pxf"),
    ("qpnoise keeps qpnoise<N>",       MIX, "", "qpss v(b) 1meg 3.1meg hb 4 1\n"
                                               "qpnoise b lin 3 100k 300k",    "qpnoise"),
    ("E-367: sweep keeps sweep<N>",    RC,  "", "sweep @r1[resistance] 500 1500 3 -analysis op", "sweep"),
    ("E-367: eye keeps eye<N>",        RC,  "", "tran 5n 4u\neye v(out) -ui 1u", "eye"),
    ("E-367: hb keeps hb<N>",          MIX, "", "hb 1meg 3",                   "hb"),
]


def main():
    # ---- [1-4] the defect: each name is its own, not a stolen one -----------
    for i, (label, net, cards, ctl, want, stolen) in enumerate(DEFECTS):
        out = run(net, cards, ctl, "d%d" % i)
        got = plots(out)
        if not got:
            check("%s names its plot %s<N>" % (label, want), False, "analysis did not run")
            continue
        check("%s names its plot %s<N>, not %s<N>" % (label, want, stolen),
              bool(pre(got, want)), brief(got))

    # ---- [5-8] the consequence: the name the command reports is selectable --
    # This is what the defect actually cost: `setplot envelope1` failed, because
    # no plot was called that. Asserting the NAME is reachable is stronger than
    # asserting the listing, since it is the operation a user performs.
    for i, (label, net, cards, ctl, want, _stolen) in enumerate(DEFECTS):
        out = run(net, cards, "%s\nsetplot %s1" % (ctl, want), "s%d" % i)
        check("setplot %s1 selects the plot %s created" % (want, label),
              current(out) == want + "1", "current = %s" % current(out))

    # ---- [9-11] the collisions, made concrete ------------------------------
    # Two DIFFERENT analyses in one session must not both answer to the same
    # abbreviation. Before the fix each of these produced e.g. pac1 and pac2,
    # with nothing in the listing to say which was which.
    out = run(MIX, ".pac 1meg 1u b 1024 10 50 5u dec 4 10k 1meg\n",
              "run\nqpss v(b) 1meg 3.1meg hb 4 1\nqpac lin 3 100k 300k", "c0")
    got = plots(out)
    check("qpac and .pac produce distinguishable plots",
          bool(pre(got, "qpac")) and bool(pre(got, "pac")), brief(got))

    out = run(SP, "", "sp lin 3 1e6 1e8\n" + SPEC, "c1")
    got = plots(out)
    check("spec and .sp produce distinguishable plots",
          bool(pre(got, "spect")) and bool(pre(got, "sp")), brief(got))

    out = run(RC, "", "op\nenvelope out 1meg 20u", "c2")
    got = plots(out)
    check("envelope and op produce distinguishable plots",
          bool(pre(got, "envelope")) and bool(pre(got, "op")), brief(got))

    # ---- [12+] ACCEPT HALF: nothing that already worked may move ------------
    # [12] is the one that matters most. "Noise SPECTral Density Curves" contains
    # "spect", so putting the spect entry above the noise entry would have
    # renamed every ordinary noise plot.
    for i, (label, net, cards, ctl, want) in enumerate(REGRESSIONS):
        got = plots(run(net, cards, ctl, "r%d" % i))
        check(label, bool(pre(got, want)), brief(got) if got else "no plot")

    # ---- [17] the invariant, asserted against the table itself --------------
    # A source check, so it holds on both binaries -- it is not a discriminator,
    # it is what stops the next entry going in the wrong place.
    tbl = os.path.join(HERE, "..", "..", "ngspice-46", "src", "frontend", "typesdef.c")
    if not os.path.isfile(tbl):
        print("  SKIP  plotabs[] ordering invariant (source tree not present)")
    else:
        def strip_c(s):
            return re.sub(r'//[^\n]*', ' ', re.sub(r'/\*.*?\*/', ' ', s, flags=re.S))
        src = open(tbl, errors="replace").read()
        raw = src[src.index("plotabs[NUMPLOTTYPES] = {"):]
        raw = raw[:raw.index("\n};")]
        ents = [(m.group(1), m.group(2)) for m in
                re.finditer(r'\{\s*"([^"]*)"\s*,\s*"([^"]*)"', strip_c(raw))]
        # every name in the tree that reaches plot_alloc(), literal or via a
        # helper. "transient"/"unknown" legitimately map to a different string.
        NAMES = {"envelope": "envelope", "eye": "eye", "hb": "hb",
                 # Enhancement-487: hbosc and phasenoise publish their own plots
                 # now. Both are shadowed by an existing pattern -- "hbosc"
                 # contains "hb", "phasenoise" contains "noise" -- so they are
                 # exactly the shape this invariant exists to catch.
                 "hbosc": "hbosc", "phasenoise": "phasenoise",
                 "loadpull": "loadpull", "qpac": "qpac", "qpnoise": "qpnoise",
                 "qpxf": "qpxf", "rfstab": "rfstab", "sp": "sp",
                 "spectrum": "spect", "stb": "stb", "sweep": "sweep",
                 "sweepwave": "sweepwave", "transient": "tran",
                 "unknown": "unknown"}
        # ... and the descriptive analName strings that reach plot_alloc(run->type)
        NAMES.update({"AC Analysis": "ac", "Transient Analysis": "tran",
                      "PAC Analysis": "pac", "PXF Analysis": "pxf",
                      "PSP Analysis": "psp", "PNoise Analysis": "pnoise",
                      "QPnoise Analysis": "qpnoise",
                      "Noise Spectral Density Curves - (V^2 or A^2)/Hz": "noise",
                      "Frequency Domain Periodic Steady State Analysis": "qpss",
                      "Time Domain Periodic Steady State Analysis": "pss",
                      "D.C. Operating point analysis": "op"})
        wrong = []
        for name, want in sorted(NAMES.items()):
            got = next((a for a, p in ents if p and p.lower() in name.lower()), "unknown")
            if got != want:
                wrong.append("%s->%s (want %s)" % (name, got, want))
        check("plotabs[] ordering invariant holds for every plot name in the tree",
              not wrong, "; ".join(wrong) if wrong else "%d names, %d entries"
              % (len(NAMES), len(ents)))

    for j in os.listdir(HERE):
        if j.startswith("_po_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
