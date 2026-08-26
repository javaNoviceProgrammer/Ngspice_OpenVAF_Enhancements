#!/usr/bin/env python3
"""Enhancement-486: twelve guards that one sibling had and the other did not.

Round 50 hunted ngspice + OSDI for an hour. OSDI itself came back clean -- state
restoration holds across all nine analyses including the new `hb` of E-483/484,
array instantiation builds real devices, out-of-range instance parameters are
refused by name, and round-34's `.dc @inst[param]` finding is still fixed. What
the hour actually found was one shape, over and over:

    the check EXISTS somewhere in the tree, and is simply absent next door.

Nine of the sixteen findings are that. Often the sibling is in the same
directory; once it is ten lines away in the same function; once it is the same
file's own history.

THE HEADLINE, `xspice/icm/table/table2D`. The data-row loop was driven by the
FILE (`while (*cThisPtr)`) and wrote `table_data[lLineCount - 1]` with no upper
bound, while every OTHER dimension of that same file was checked -- the x row,
the y row, the width of each individual data row, even a premature EOF inside the
comment block. A file declaring 3 y values and supplying 5 data rows indexed past
the allocation and SEGFAULTED (EXC_BAD_ACCESS at 0x0 in cm_table2D), rc = 139,
with no diagnostic at all. Too FEW rows was the mirror: the shortfall stayed as
calloc's zeros and a probe in the missing region returned 0.0, a perfectly
plausible "no current". Enhancement-247 had already worked in this very file --
"fix OOB READ + interpolation UB on degenerate/too-small tables" -- and left the
WRITE and the too-many case untouched. The sibling table3D refuses the truncated
file outright ("Not enough data in file"), so the two disagreed about one input.

THE SECOND HEADLINE, `spicelib/analysis/cktsens.c`. count_steps() is declared to
return a POINT COUNT, and Enhancement-362's overflow guard signalled failure from
it with `return(E_PARMVAL)`. E_PARMVAL is 11, and the sole caller assigned the
result straight to nfreqs without an error test -- so an "impossible" sweep ran
ELEVEN points, and because that return happened before `*stepsize = s` the step
was never written and every frequency after the first collapsed to zero. Below it
sat two silent repairs of values the USER STATED: a DEC/OCT sweep starting at 0 Hz
had `low` rewritten to 1e-3, and a stop at or below the start had `high` rewritten
to a decade above it -- and both rewrote only the LOCAL copy, so the count came
from the repaired bounds while the sweep still ran from job->start_freq. That is
why `.sens ac dec 5 0 1meg` printed a full table of 0 Hz rows and `.sens ac dec 5
1k 1k` swept a full decade past the stop asked for. .ac, .noise, .disto and .sp
all get both cases right; the rules here are now .ac's own.

WITHDRAWN AT FIX TIME, and the reason this suite pins them:
  * NEGATIVE capacitance and inductance are NOT defects. The built-in C device
    accepts C = -1u and produces exactly the sign-inverted response the XSPICE
    model produces; the built-in L device diverges the same way at L = -1u. The
    two agree, so a negative reactance is a legitimate equivalent-circuit element
    here. Only c = 0 / l = 0 -- a real division by zero that surfaced as "Timestep
    too small; cause unrecorded" -- is fixed. Checks [8]-[11] hold that line.
  * mlin's `rho = 0` looked like a legitimate "perfect conductor" idealisation
    and was first classified as such. Measuring it returned a bare NaN, so it is
    strictly positive after all -- while t, tand and d at zero are genuinely fine.
    Checks [37]-[39] hold both halves of that distinction.
  * xfer's DUPLICATE frequencies stay legal, because the `table` path of the same
    model deliberately allows them. The fix makes the file path apply the table
    path's rule, not a stricter one of its own. Check [27].
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
    return ok


def run(deck, ctl, tag, timeout=120):
    path = os.path.join(HERE, f"_gp_{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* guardpair {tag}\n{deck}\n.control\noption noacct\nset numdgt=12\n"
                f"{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", "-r", os.devnull, path], capture_output=True,
                           text=True, timeout=timeout, cwd=HERE, stdin=subprocess.DEVNULL)
        rc, out = r.returncode, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        rc, out = None, "TIMEOUT"
    try:
        os.remove(path)
    except OSError:
        pass
    return rc, out


def val(out, name):
    """Anchored to the start of a line -- round 49 lost a finding because an
    unanchored read matched a card ECHOED inside a diagnostic."""
    m = re.findall(r"(?m)^\s*" + re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out)
    return float(m[-1]) if m else None


def rows(out):
    return int(m.group(1)) if (m := re.search(r"No\. of Data Rows : (\d+)", out)) else None


def said(out, *frags):
    return any(all(f in line for f in frags) for line in out.splitlines())


def write(name, text):
    p = os.path.join(HERE, name)
    with open(p, "w") as f:
        f.write(text)
    return name


# --------------------------------------------------------------- data files
XS = [0.0, 0.25, 0.5, 0.75, 1.0]


def table2d(name, ny_declared, nrows):
    ys = [0.0, 0.25, 0.5, 0.75, 1.0][:ny_declared]
    body = f"*guardpair 2D\n*x\n{len(XS)}\n*y\n{ny_declared}\n*x row\n"
    body += " ".join(repr(v) for v in XS) + "\n*y column\n"
    body += " ".join(repr(v) for v in ys) + "\n"
    for j in range(nrows):
        yv = ys[j] if j < len(ys) else ys[-1]
        body += " ".join(repr(1e-3 * (x + yv)) for x in XS) + "\n"
    return write(name, body)


T_OK = table2d("_gp_ok.table", 5, 5)
T_MANY = table2d("_gp_many.table", 3, 5)
T_FEW = table2d("_gp_few.table", 5, 3)

TAB2D = ('Vx x 0 0.5\nVy y 0 0.5\nVs s 0 0\n'
         'atab %vd(x 0) %vd(y 0) %id(s 0) tm\n'
         '.model tm table2d (offset=0.0 gain=1.0 order=3 file="{f}")\n')

print("\ntable2D: the data-row count was the one dimension never checked")
rc, o = run(TAB2D.format(f=T_OK), "op\nlet i=i(Vs)\nprint i", "t2ok")
check("[1] a well-formed 5x5 table still answers exactly", val(o, "i") == -0.001, str(val(o, "i")))
rc, o = run(TAB2D.format(f=T_MANY), "op\nlet i=i(Vs)\nprint i", "t2many")
check("[2] too MANY rows no longer segfaults", rc not in (-11, 139), f"rc={rc}")
check("[3] ...and the row count is named", said(o, "Too many data rows"), "named")
rc, o = run(TAB2D.format(f=T_FEW), "op\nlet i=i(Vs)\nprint i", "t2few")
check("[4] too FEW rows is refused, not answered from calloc's zeros",
      rc != 0 and val(o, "i") is None, f"rc={rc} i={val(o,'i')}")
check("[5] ...and the shortfall is named", said(o, "Not enough data rows"), "named")


def table3d(name, ntab, nrow):
    zs = [0.0, 0.5, 1.0]
    ys = [0.0, 0.5, 1.0]
    xs = [0.0, 0.5, 1.0]
    b = f"*guardpair 3D\n*x\n3\n*y\n3\n*z\n3\n*x row\n" + " ".join(map(repr, xs))
    b += "\n*y column\n" + " ".join(map(repr, ys)) + "\n*z tables\n" + " ".join(map(repr, zs)) + "\n"
    for k, z in enumerate(zs[:ntab]):
        b += f"*table {z!r}\n"
        for j in range(nrow):
            yv = ys[j] if j < len(ys) else ys[-1]
            b += " ".join(repr(1e-3 * (x + yv + z)) for x in xs) + "\n"
    return write(name, b)


T3_OK = table3d("_gp_ok3.table", 3, 3)
T3_EXTRA = table3d("_gp_extra3.table", 3, 6)
TAB3D = ('Vx x 0 0.5\nVy y 0 0.5\nVz z 0 0.5\nVs s 0 0\n'
         'a1 x y z %id(s 0) tm\n.model tm table3d(offset=0 gain=1 order=2 file="{f}")\n')

print("\ntable3D: bounded already, but silent about a file it had to truncate")
rc, o = run(TAB3D.format(f=T3_OK), "op\nlet i=i(Vs)\nprint i", "t3ok")
check("[6] a well-formed 3x3x3 table still answers exactly", val(o, "i") == -0.0015, str(val(o, "i")))
rc, o = run(TAB3D.format(f=T3_EXTRA), "op\nlet i=i(Vs)\nprint i", "t3ex")
check("[7] surplus data is now reported rather than dropped in silence",
      said(o, "carries data past"), "warned")

print("\nd_state: a transition to a state the file never defines")
write("_gp_st.txt", "0  0s 0s  0 -> 3\n          1 -> 1\n1  0s 1z  0 -> 0\n          1 -> 2\n"
                    "2  1z 0s  0 -> 1\n          1 -> 3\n3  1z 1z  0 -> 2\n3  1z 1z  1 -> 0\n")
write("_gp_stbad.txt", "0  0s 0s  0 -> 77\n          1 -> 88\n1  0s 1z  0 -> 77\n          1 -> 88\n"
                       "2  1z 0s  0 -> 77\n          1 -> 88\n3  1z 1z  0 -> 77\n3  1z 1z  1 -> 88\n")
DST = ('Vclk clk0 0 pulse(0 1 0 0.1n 0.1n 4.9n 10n)\n'
       'Vin in0 0 pulse(0 1 0 0.1n 0.1n 24.9n 50n)\nVrst rst0 0 {rst}\n'
       'Ab [clk0 in0 rst0] [clk up reset] adc\n.model adc adc_bridge(in_low=0.3 in_high=0.7)\n'
       'Acnt [up] clk reset [o1 o2] stm\n'
       '.model stm d_state(clk_delay=0.1n reset_delay={rd} state_file="{f}" reset_state=0)\n'
       'Ad [o1 o2] [b1 b2] dac\n.model dac dac_bridge(out_low=0 out_high=1)\n'
       'Rb1 b1 0 1k\nRb2 b2 0 1k')
rc, o = run(DST.format(f="_gp_st.txt", rd="0.1n", rst="0"),
            "tran 0.5n 100n\nlet mx=maximum(v(b1))\nprint mx", "dsok")
check("[8] a well-formed state file still runs the machine", val(o, "mx") == 1.0, str(val(o, "mx")))
check("[9] ...and says nothing about undefined states", not said(o, "no row of the state"), "quiet")
rc, o = run(DST.format(f="_gp_stbad.txt", rd="0.1n", rst="0"),
            "tran 0.5n 100n\nlet mx=maximum(v(b1))\nprint mx", "dsbad")
check("[10] an undefined next state is named instead of silently selecting row 0",
      said(o, "no row of the state"), "named")
check("[11] ...and the offending state number is given", said(o, "77") or said(o, "88"), "numbered")

print("\ncapacitoric / inductoric: zero is the division; NEGATIVE stays legal")
REACT = 'V1 in 0 sin(0 1 1meg)\nR1 in a 1k\nA1 a 0 X1\n.model X1 {m}({p}={v})\n'
BUILTIN = 'V1 in 0 sin(0 1 1meg)\nR1 in a 1k\n{d}\n'
rc, o = run(REACT.format(m="capacitoric", p="c", v="0"),
            "tran 10n 3u\nlet mn=minimum(v(a))\nprint mn", "c0")
check("[12] capacitoric c=0 is refused by name, not as 'Timestep too small'",
      rc != 0 and said(o, "CAPACITOR: c = 0 is not a usable value"), f"rc={rc}")
rc, o = run(REACT.format(m="inductoric", p="l", v="0"),
            "tran 10n 3u\nlet mn=minimum(v(a))\nprint mn", "l0")
check("[13] inductoric l=0 likewise", rc != 0 and said(o, "INDUCTOR: l = 0 is not a usable value"),
      f"rc={rc}")
rc, o = run(REACT.format(m="capacitoric", p="c", v="-1u"),
            "tran 10n 3u\nlet mn=minimum(v(a))\nprint mn", "cneg")
xc = val(o, "mn")
rc2, o2 = run(BUILTIN.format(d="C1 a 0 -1u"), "tran 10n 3u\nlet mn=minimum(v(a))\nprint mn", "cnegb")
bc = val(o2, "mn")
check("[14] a NEGATIVE capacitance still runs -- it is not a defect", rc == 0 and xc is not None,
      f"rc={rc} min={xc}")
check("[15] ...and still agrees with the BUILT-IN C device, which allows it too",
      xc is not None and bc is not None and abs(xc - bc) < 1e-6 * max(1.0, abs(bc)),
      f"xspice={xc} builtin={bc}")
rc, o = run(REACT.format(m="capacitoric", p="c", v="1u"),
            "tran 10n 3u\nlet mx=maximum(v(a))\nprint mx", "cok")
check("[16] an ordinary capacitance is untouched", rc == 0 and val(o, "mx") is not None,
      str(val(o, "mx")))

print("\n.sens ac: count_steps() repaired the user's bounds and mis-signalled errors")
SENSD = 'V1 in 0 dc 0 ac 1\nR1 in a 1k\nC1 a 0 1n\nR2 a 0 10k\n'
def sens(sw, tag):
    return run(SENSD + f".sens v(a) ac {sw}\n", "run", tag)
rc, o = sens("dec 5 1k 1meg", "sv")
check("[17] a valid decade sweep is unchanged", rows(o) == 16, f"rows={rows(o)}")
rc, o = sens("dec 5 0 1meg", "s0d")
check("[18] dec starting at 0 Hz is refused, not run as a table of 0 Hz rows",
      said(o, "SENS AC startfreq <= 0"), "named")
rc, o = sens("oct 5 0 1meg", "s0o")
check("[19] oct starting at 0 Hz likewise", said(o, "SENS AC startfreq <= 0"), "named")
rc, o = sens("lin 5 0 1meg", "s0l")
check("[20] lin from 0 Hz is still allowed -- there 0 Hz is a legitimate DC point",
      rows(o) == 5, f"rows={rows(o)}")
for sw, tag, lbl in [("dec 5 1k 1k", "se1", "[21] dec"), ("oct 5 1k 1k", "se2", "[22] oct"),
                     ("lin 5 1k 1k", "se3", "[23] lin")]:
    rc, o = sens(sw, tag)
    check(f"{lbl} with stop == start gives the single point .ac gives", rows(o) == 1,
          f"rows={rows(o)}")
rc, o = run(SENSD + ".ac dec 5 1k 1k\n", "run", "seac")
check("[24] ...which is what .ac itself produces, for the same card", rows(o) == 1,
      f"rows={rows(o)}")
rc, o = sens("dec 5 1meg 1k", "sback")
# Refused by Enhancement-485's parse-time inp_sweep_args_ok, which already covered
# stop < start; the count_steps() test added here is the same refusal one layer
# down, and is what catches the case when count_steps is reached directly.
check("[25] a stop below the start is refused",
      said(o, "must not be less than the start frequency"), "named")
rc, o = sens("dec 2000000000 1 100", "sovf")
check("[26] an unrepresentable point count is refused, not run as ELEVEN points",
      rows(o) != 11 and said(o, "not representable"), f"rows={rows(o)}")

print("\nfile_source: the file-driven sibling of pwl, which has required monotonic x since E-480")
write("_gp_fs_ok.txt", "0.0 0.0\n1e-6 1.0\n2e-6 0.0\n3e-6 1.0\n")
write("_gp_fs_back.txt", "0.0 0.0\n3e-6 1.0\n1e-6 0.0\n2e-6 1.0\n")
write("_gp_fs_dup.txt", "0.0 0.0\n1e-6 1.0\n1e-6 0.0\n2e-6 1.0\n")
write("_gp_fs_neg.txt", "0.0 0.0\n-1e-6 1.0\n2e-6 0.0\n")
FS = ('A1 [a] src\n.model src filesource(file="{f}" amploffset=[0] amplscale=[1])\nRa a 0 1k\n')
rc, o = run(FS.format(f="_gp_fs_ok.txt"), "tran 1e-7 3e-6\nlet mx=maximum(v(a))\nprint mx", "fsok")
check("[27] an increasing time column still drives the source", rc == 0 and val(o, "mx") == 1.0,
      str(val(o, "mx")))
for f, tag, lbl in [("_gp_fs_back.txt", "fsb", "[28] a time column that steps BACKWARDS"),
                    ("_gp_fs_dup.txt", "fsd", "[29] a REPEATED time"),
                    ("_gp_fs_neg.txt", "fsn", "[30] a time that goes NEGATIVE")]:
    rc, o = run(FS.format(f=f), "tran 1e-7 3e-6\nlet mx=maximum(v(a))\nprint mx", tag)
    check(f"{lbl} is refused by name", rc != 0 and said(o, "must increase monotonically"),
          f"rc={rc}")

print("\nxfer: the file path never applied the rule its own table path already applies")
write("_gp_xf_ok.txt", "# Hz DB\n1.0 0.0 0.0\n10.0 -3.0 -45.0\n100.0 -20.0 -90.0\n1000.0 -40.0 -90.0\n")
write("_gp_xf_back.txt", "# Hz DB\n1.0 0.0 0.0\n1000.0 -40.0 -90.0\n10.0 -3.0 -45.0\n100.0 -20.0 -90.0\n")
write("_gp_xf_neg.txt", "# Hz DB\n-100.0 0.0 0.0\n10.0 -3.0 -45.0\n100.0 -20.0 -90.0\n")
write("_gp_xf_dup.txt", "# Hz DB\n1.0 0.0 0.0\n1.0 -3.0 -45.0\n100.0 -20.0 -90.0\n")
XF = 'V1 in 0 ac 1\nA1 %vd(in 0) %vd(out 0) X\n.model X xfer(file="{f}")\nRo out 0 1meg\n'
rc, o = run(XF.format(f="_gp_xf_ok.txt"), "ac dec 5 1 1k\nlet mx=maximum(mag(v(out)))\nprint mx", "xfok")
base = val(o, "mx")
check("[31] a well-formed Touchstone file is unchanged", base is not None and base > 1.0, str(base))
rc, o = run(XF.format(f="_gp_xf_back.txt"), "ac dec 5 1 1k\nlet mx=maximum(mag(v(out)))\nprint mx", "xfb")
check("[32] an out-of-order frequency column is named", said(o, "badly formed frequency"), "named")
rc, o = run(XF.format(f="_gp_xf_neg.txt"), "ac dec 5 1 1k\nlet mx=maximum(mag(v(out)))\nprint mx", "xfn")
check("[33] a negative frequency is named", said(o, "badly formed frequency"), "named")
rc, o = run(XF.format(f="_gp_xf_dup.txt"), "ac dec 5 1 1k\nlet mx=maximum(mag(v(out)))\nprint mx", "xfd")
check("[34] a REPEATED frequency stays legal -- the table path allows it, so the file path does too",
      not said(o, "badly formed frequency"), "allowed")
rc, o = run(XF.format(f="_gp_nosuch.txt"), "ac dec 5 1 1k\nlet mx=maximum(mag(v(out)))\nprint mx", "xfm")
check("[35] a missing file now states what it COSTS, not just that it failed",
      said(o, "contribute nothing"), "consequence stated")

print("\nhyst: input_domain was the one way out of its own out_lower/out_upper_limit")
HY = ('Vi in 0 pulse(0 5 0 1u 1u 1u 4u)\nA1 in out H\n'
      '.model H hyst(in_low=1 in_high=4 hyst=0.5 out_lower_limit=0 out_upper_limit=1 '
      'input_domain={v} fraction=true)\nRo out 0 1k\n')
for v, tag, lbl in [("0.1", "hy1", "[36] a sane input_domain"),
                    ("-0.1", "hy2", "[37] a negative input_domain"),
                    ("10", "hy3", "[38] input_domain=10"),
                    ("1e6", "hy4", "[39] input_domain=1e6 (was 250,000x above the limit)")]:
    rc, o = run(HY.format(v=v), "tran 50n 8u\nlet mx=maximum(v(out))\nlet mn=minimum(v(out))\n"
                                "print mx\nprint mn", tag)
    mx, mn = val(o, "mx"), val(o, "mn")
    check(f"{lbl} keeps the output inside [out_lower_limit, out_upper_limit]",
          mx is not None and mn is not None and mx <= 1.0000001 and mn >= -1e-7,
          f"{mn} .. {mx}")

print("\ncore: h_array/b_array, the paired-length check pwl has carried all along")
CORE = ('Vm m 0 sin(0 500 1k)\nA1 m 0 C\n'
        '.model C core(h_array=[-1000 -500 0 500 1000] b_array={b} area=1e-4 length=0.1 '
        'input_domain=0.01 fraction=true)\nRm m 0 1e6\n')
rc, o = run(CORE.format(b="[-1.5 -1.0 0 1.0 1.5]"), "tran 10u 2m\nlet mx=maximum(v(m))\nprint mx", "co1")
check("[40] a matched pair of arrays still runs", rc == 0 and val(o, "mx") is not None, f"rc={rc}")
rc, o = run(CORE.format(b="[-1.5 0 1.5]"), "tran 10u 2m\nlet mx=maximum(v(m))\nprint mx", "co2")
check("[41] a SHORTER b_array is refused instead of read past its end",
      rc != 0 and said(o, "same length"), f"rc={rc}")
rc, o = run(CORE.format(b="[-1.5 -1.2 -1.0 -0.5 0 0.5 1.0 1.5]"),
            "tran 10u 2m\nlet mx=maximum(v(m))\nprint mx", "co3")
check("[42] a LONGER b_array is refused too", rc != 0 and said(o, "same length"), f"rc={rc}")

print("\nmlin / cpline / cpmlin: geometry that cannot exist")
ML = 'V1 in 0 ac 1\nRs in a 50\nA1 a 0 b 0 a 0 b 0 ml\n.model ml mlin({ex})\nRL b 0 50\n'
rc, o = run(ML.format(ex=""), "ac lin 1 1g 1g\nlet m1=mag(v(b))\nprint m1", "ml0")
check("[43] a default microstrip is unchanged", rc == 0 and val(o, "m1") is not None, str(val(o, "m1")))
for ex, tag, lbl in [("l=-1e-2", "ml1", "[44] a NEGATIVE length (gave a plausible wrong answer)"),
                     ("l=0", "ml2", "[45] a zero length (gave a bare nan)"),
                     ("w=0", "ml3", "[46] a zero width"),
                     ("er=-9.8", "ml4", "[47] a negative permittivity"),
                     ("rho=-1", "ml5", "[48] a negative resistivity"),
                     ("rho=0", "ml6", "[49] rho=0 -- NOT a usable idealisation, it returns nan")]:
    rc, o = run(ML.format(ex=ex), "ac lin 1 1g 1g\nlet m1=mag(v(b))\nprint m1", tag)
    check(f"{lbl} is refused by name", rc != 0 and said(o, "MLIN:", "not a usable value"), f"rc={rc}")
for ex, tag, lbl in [("t=0", "mt1", "[50] t=0 (a zero-thickness strip)"),
                     ("tand=0", "mt2", "[51] tand=0 (a lossless dielectric)"),
                     ("d=0", "mt3", "[52] d=0 (a smooth conductor)")]:
    rc, o = run(ML.format(ex=ex), "ac lin 1 1g 1g\nlet m1=mag(v(b))\nprint m1", tag)
    m1 = val(o, "m1")
    check(f"{lbl} stays legal -- it is an ordinary idealisation",
          rc == 0 and m1 is not None, f"rc={rc} m1={m1}")
P8 = "n1 0 n2 0 n3 0 n4 0 n1 0 n2 0 n3 0 n4 0"
CP = ('V1 in 0 ac 1\nRs in n1 50\nA1 ' + P8 + ' X\n.model X {m}({ex})\n'
      'R2 n2 0 50\nR3 n3 0 50\nR4 n4 0 50\n')
for m, ok, bad, t in [("cpline", "l=1e-2 ze=50 zo=40 ere=3 ero=3 ae=0 ao=0",
                       "l=-1e-2 ze=50 zo=40 ere=3 ero=3 ae=0 ao=0", "cl"),
                      ("cpmlin", "l=1e-2 w=1e-3 s=1e-3", "l=-1e-2 w=1e-3 s=1e-3", "cm")]:
    rc, o = run(CP.format(m=m, ex=ok), "ac lin 1 1g 1g\nlet m1=mag(v(n2))\nprint m1", t + "ok")
    check(f"[{53 if m=='cpline' else 55}] a valid {m} is unchanged",
          rc == 0 and val(o, "m1") is not None, f"rc={rc}")
    rc, o = run(CP.format(m=m, ex=bad), "ac lin 1 1g 1g\nlet m1=mag(v(n2))\nprint m1", t + "bad")
    check(f"[{54 if m=='cpline' else 56}] {m} with a negative length is refused by name",
          rc != 0 and said(o, "not a usable value"), f"rc={rc}")

print("\npoly(): the two faults were each reported with the other's message")
POLY = 'V1 a 0 1\nV2 b 0 2\n{card}\nRo out 0 1k\n'
rc, o = run(POLY.format(card="E1 out 0 POLY(2) a 0 b 0"), "op\nprint v(out)", "pv1")
check("[57] too few COEFFICIENTS no longer claims the CONNECTIONS are wrong",
      not said(o, "Number of connections differs"), "old wording gone")
check("[58] ...and the arithmetic is shown instead", said(o, "poly(2) needs"), "named")
rc, o = run(POLY.format(card="E1 out 0 POLY(3) a 0 b 0 1 1 1"), "op\nprint v(out)", "pv2")
check("[59] too few NODE PAIRS now says so, instead of only blaming 'coef'",
      said(o, "INPUT NODE PAIRS"), "hinted")
rc, o = run(POLY.format(card="E1 out 0 POLY(2) a 0 b 0 0 1 1"), "op\nprint v(out)", "pv3")
check("[60] a valid truncated poly is untouched", val(o, "v(out)") == 3.0, str(val(o, "v(out)")))

print("\ndeclared Limits: the parse-time refusal 20+ siblings already had")
rc, o = run(DST.format(f="_gp_st.txt", rd="-1n", rst="pulse(0 1 30n 0.1n 0.1n 10n 200n)"),
            "tran 0.5n 100n\nlet mx=maximum(v(b1))\nprint mx", "dl1")
check("[61] d_state reset_delay < 0 is named at parse time, by parameter",
      said(o, "below limit", "reset_delay"), "named")
check("[62] ...and the per-event 'Output delay < 0' storm is gone",
      not said(o, "Output delay < 0"), "clamped")
rc, o = run(DST.format(f="_gp_st.txt", rd="0.1n", rst="0"),
            "tran 0.5n 100n\nlet mx=maximum(v(b1))\nprint mx", "dl2")
check("[63] a sane reset_delay draws no limit message at all",
      not said(o, "below limit"), "quiet")
rc, o = run('Vs s 0 pulse(0 1 0 1n 1n 10n 20n)\nAa [s] [d] adc\n.model adc adc_bridge\n'
            'Ab d r dr\n.model dr d_to_real(zero=0 one=1 delay=1e-9)\n'
            'Ac r r2 G\n.model G real_gain(gain=1 delay=-1e-9)\n', "op\nprint 1", "rg1")
check("[64] real_gain delay < 0 is named, as its sibling real_delay already was",
      said(o, "below limit", "delay"), "named")
rc, o = run('Vc clk 0 pulse(0 1 1u 1n 1n 1u 5u)\nVi ci 0 1\nVl clr 0 0\n'
            'A1 clk ci clr out OS\n.model OS oneshot(rise_delay=-1 fall_delay=-1)\nRo out 0 1k\n',
            "op\nprint 1", "os1")
check("[65] oneshot rise_delay/fall_delay < 0 is named",
      said(o, "below limit"), "named")

# ------------------------------------------------------------------ cleanup
for f in os.listdir(HERE):
    if f.startswith("_gp_"):
        try:
            os.remove(os.path.join(HERE, f))
        except OSError:
            pass

print(f"\n=== {passed}/{checks} checks passed ===")
sys.exit(0 if passed == checks else 1)
