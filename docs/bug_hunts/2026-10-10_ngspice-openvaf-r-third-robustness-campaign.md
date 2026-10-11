# Bug hunt — ngspice and openvaf-r: a third robustness and correctness campaign, under Sparse and KLU

**When:** 2026-10-10, after the [second campaign](2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md)
was folded (E-845 to E-855).
**Binaries:** the repo's `ngspice-46/build/src/ngspice` and
`OpenVAF-master-20260610/target/opt/openvaf-r`, both at E-855. Tree at `fb4d37ce`.

**Method:** eight families of generated checks, none repeating the first two campaigns. Every
deck ran twice, under `.option sparse` and under `.option klu`, and each solver's result was
checked against the reference and against the other. They ran one simulation at a time under a
12 GB RSS cap, through throwaway harnesses in the session scratchpad (`rc3/*.py`). Each
reference shares no code with the thing under test:

- **A. AC of random linear networks against the exact complex solve.** 300 networks of R, C,
  L, mutual K, V and I sources with phase, and E, F, G, H sources. The reference is my own MNA
  in numpy, solved at each of ngspice's frequencies: 10 454 points. A second run of 300
  inductor-heavy networks swept from 0.1–10 Hz upward: 10 814 points.
- **B. Constant expressions through ngspice's three parsers.** 4 000 random expressions over
  the grammar all three accept: `+ - * / ^`, unary minus, scale suffixes, and 14 functions.
  Each is evaluated by a `.param` (numparam), a B-source (both under each solver) and `let`,
  and compared with Python. Then a curated table of 88 edge cases.
- **C. `.tf`, `.sens` and `.pz` against exact values.**
  - 300 resistive networks with controlled sources give the gain, input and output resistance,
    and 12 282 dc sensitivities, from the exact solve and its adjoint.
  - 300 small RC/RLC networks with E and G sources give poles and zeros. The poles are the
    finite generalized eigenvalues of the MNA pencil, the zeros those of its Rosenbrock pencil;
    2 042 roots.
- **D. Nonlinear networks, Sparse against KLU.** 200 random networks of diodes, BJTs and
  level-1 MOSFETs: op, a dc sweep and a transient, compared between the solvers.
- **E. OSDI twins against built-in elements.** 150 linear networks with half their 1 355
  elements replaced by Verilog-A twins (R with its thermal noise, C, L, VCCS): op, ac, noise
  and transient, against the all-built-in run.
- **F. Command sequences against fresh sessions.** 840 sequences on a small diode and BJT
  circuit. Each runs analyses, `alter`, `altermod`, `reset` or `set temp`, then a measured
  analysis, compared with the same analysis in a fresh session on the netlist the commands
  describe.
- **G. Factorization stress.** 300 linear networks with values over 15 decades,
  capacitor-only sub-networks, and zero-gain controlled sources: ac against the exact solve
  within the condition-number bound; 8 946 points.
- **H. Collapsing Verilog-A networks.** A module with three internal nodes, each of whose
  three resistors collapses its branch to a short at 0, in 300 circuits with 561 collapsed
  branches: op, ac and transient against the same network of built-in elements.

Nothing was fixed; this is the list.

| | Finding | Severity |
|---|---|---|
| [F1](#f1) | *(fixed in [E-856](../../enhancements_doc/Enhancement-856.md): a found root is divided out analytically, a pair on the jω axis is declared, and the noise beyond the last root is not taken for a root; the runs did warn)* **pz, wrong result:** `.pz` silently returns a wrong set of poles and zeros on 4 of 252 networks, once under KLU only. The roots it gives miss ngspice's own ac response by 240 % to 450 %; the exact roots reproduce it to 1e-13 | high |
| [F2](#f2) | *(fixed in [E-857](../../enhancements_doc/Enhancement-857.md): a sign after an operator takes the power chain after it, as in the B-source, and `let` takes a unary plus)* **expressions, wrong value:** in a `.param`, a unary minus after a binary operator works only before a number. Before a name, a parenthesis or a function, `{2*-p}`, `{1/-(2)}` and `{x*-sin(y)}` give "Formula() error" and the netlist is not loaded: 114 of the 4 000 random expressions. Before another minus, one sign is dropped without a word: `{2*--2}` is −4, `{0+--2}` is −2, `{2---2}` is 4. The B-source gets all of them right, and `let` all but the unary plus | high |
| [F3](#f3) | *(fixed in [E-858](../../enhancements_doc/Enhancement-858.md): `mil` is 25.4e-6 in a `.param` too, an exponent and a suffix fold into one exact decimal, and the value reaches the element with 17 digits)* **expressions, wrong value:** `mil` is 25.4e-6 as an element value, in a B-source and in `let`, and 1e-3 in a `.param` | medium |
| [F4](#f4) | *(fixed in [E-859](../../enhancements_doc/Enhancement-859.md): the front end reads the scale factor after the exponent, the netlist's value to the bit)* **expressions, wrong value:** `let` drops a scale suffix after an exponent: `let x = 1.5e2u` is 150, where a netlist reads 1.5e-4 | medium |
| [F5](#f5) | *(fixed in [E-860](../../enhancements_doc/Enhancement-860.md): one step of iterative refinement after the ac solve where the residual says so)* **ac accuracy:** with the default `pivrel` of 1e-3, the ac solve of inductive networks at low frequency loses up to 6 digits on matrices of condition 5: 22 of 300 networks under Sparse (up to 3.4e-6), 5 under KLU (2e-7). `pivrel=1` gives 1e-16 | medium |
| [F6](#f6) | *(fixed in [E-861](../../enhancements_doc/Enhancement-861.md): a central difference where the parameter is not zero)* **sens accuracy:** every dc sensitivity to a resistance is low by a factor of exactly 1 − 1e-6; to a gain or a source it is exact to 1e-10 | low |
| [F7](#f7) | **constants, openvaf-r:** inside one model, `$vt(T)` and `` `P_K*T/`P_Q `` differ by 1.05e-6; the compiler's comment says they agree. Both differ from ngspice's kT/q, so a Verilog-A resistor's thermal noise is up to 6.4e-7 above the built-in one's | low |
| [F8](#f8) | **front end:** `let x = tan(0)` fails "argument out of range for tan" | low |
| [F9](#f9) | **front end:** `%` on a complex vector refuses every real divisor: `v(1) % 2` after an ac fails "argument out of range for mod" | low |
| [F10](#f10) | **expressions:** `2^3^2` is 64 in a `.param` and a B-source, and 512 in `let`. The manual's precedence table puts unary minus above `**`, which would make `-2^2` 4; all three give −4 | low |
| [F11](#f11) | **output:** `write` names a pz plot's vectors `v(pole(2))` and `v(zero(1))`, and adds a duplicate `v(all)` to a plot with one pole; `print all` prints that pole as `all = …` | low |

<a id="f1"></a>
## F1 — `.pz` returns a wrong set of poles and zeros

*Fixed in [E-856](../../enhancements_doc/Enhancement-856.md). The four runs were not silent: each
printed "Pole-zero iteration limit reached; giving up after N trials with K roots found", which
this page missed. The dig found why the search gave up. Each root it found was divided out of
the function by |p − s|², which isn't analytic at a complex trial, so Muller wandered around a
pair it had started next to. A pair on the jω axis was found to the last digit and never
declared, because the test of a repeated point measured the real part against |Re s| = 0. Now:
- the factor is (p − s), or (p − s)(p̄ − s) for a pair;
- a repeated complex point is tested against |s|;
- a point beyond the last root, where s·C swamps G, is a root only if the function grows around
  it as at a zero.

All 252 networks match the exact roots under both solvers. On 859 more, E-855 had 18 runs with
a wrong set, 2 of them without a warning; now none, apart from a zero at 1.7e-6 among roots of
1e5 to 1e9, which the search reports as 0.*

```spice
* pz 1233 (scratchpad rc3/min/pz_1233.cir), no source at the input port
...
.control
pz 1 0 2 0 vol pz
print all
```

The exact poles are −4.39e7, −1.77e7 and −1.48e7 ± 5.40e6j, and the zeros −4.39e7, −1.77e7 and
±1.58e7j, so two pairs cancel. ngspice gives the four zeros and a single pole, −1.77e7. It
misses the pole at −4.39e7 and the complex pair, so what it reports has a zero at −4.39e7
that nothing cancels and no complex poles. Three other networks lose zeros:
- 1036 finds 1 of 4;
- 1088 misses a complex pair;
- 1250 misses a pair on the jω axis under KLU only; Sparse finds it.

Every run is silent.

The check that settles which set is right is ngspice's own ac response of the same network.
The rational function of the exact roots reproduces it to between 1e-13 and 1e-16, after
fitting the gain. The one of ngspice's roots misses it by 240 % to 450 %:

| seed | exact roots | ngspice's roots |
|---|---|---|
| 1233 | 8.9e-16 | 3.0 |
| 1250 (KLU) | 6.3e-16 | 2.4 |
| 1036 | 2.2e-14 | 4.5 |
| 1088 | 1.9e-13 | 2.7 |

The other 248 networks, 2 042 roots in all, match to 1e-8 under both solvers. 48 more have a
transfer function that is identically zero. They were left out; the three looked at are
refused with "the input signal is shorted on the way to the output".

<a id="f2"></a>
## F2 — a unary minus after an operator in a `.param`

*Fixed in [E-857](../../enhancements_doc/Enhancement-857.md). A sign after an operator now takes
the power chain after it as its operand, as the B-source's grammar does, and is evaluated as an
atom. The dig found a third form, silent like the second: the flag negated the number before `^`
saw it. So `{2*-3^2}` was 18 where the B-source gives −18; this page's generator always
bracketed its power chains. `let` takes a unary plus.*

```spice
.param p = 3
.param a = {2*-3}
.param b = {2*-p}
.param c = {2*--2}
```

`a` is −6. `b` fails "Formula() error", and since a numparam error stops the netlist, nothing
runs. After a binary operator, numparam takes a unary minus only before a number. These are
refused:
- before a name: `{2*-p}`, `{2 * - p}`;
- before a parenthesis: `{1/-(2)}`, `{2^-(1)}`;
- before a function: `{2*-sin(1)}`.

A unary plus there is refused even before a number, `{2*+3}`. All 114 refusals among the 4 000
random expressions have one of these forms; every other expression evaluates as the B-source
and `let` do.

Before another minus, there is no error and one sign is lost:

| expression | `.param` | B-source, and the value |
|---|---|---|
| `2*--2` | −4 | 4 |
| `0+--2` | −2 | 2 |
| `1/--2` | −0.5 | 0.5 |
| `2^--1` | 0.5 | 2 |
| `2---2` | 4 | 0 |

`--2` alone and `2*(--2)` are right, and so are values passed through subcircuit parameters:
`k=-2` reaching `{0-k}` gives 2. `{-p*2}`, `{p*-1}` and `{2*(-p)}` all work, so the refusal is
easy to step around once it is understood. The wrong sign is not, since nothing reports it.

<a id="f3"></a>
## F3 — `mil` is milli in a `.param`

*Fixed in [E-858](../../enhancements_doc/Enhancement-858.md). `mil` is 25.4e-6 in a `.param`, as
in the netlist. The dig found two more drifts from the netlist's reading of the same text. A
mantissa with its own exponent was multiplied by the suffix, a second rounding, which put 37 of
300 such spellings an ulp off. And the value went back into the deck with 16 significant digits,
so `{0.1+0.2}` reached the element as 0.3. Both are fixed: 316 suffixed spellings now give one
double through an element value, a `.param`, a B-source and `let`.*

```spice
.param p = {1mil}
r1 1 0 1mil
b3 3 0 v = 1mil
```

`r1` is 25.4e-6 Ω, as the manual's scale-factor table (§2.1.3.2) says, and so are the
B-source and `let x = 1mil`. `{1mil}` is 1e-3: numparam's own suffix table (§2.11) has no
`mil`, so it reads `m` and lets "il" go as decoration. The same text means two values 39 times
apart in one netlist, without a word.

<a id="f4"></a>
## F4 — `let` drops a scale suffix after an exponent

*Fixed in [E-859](../../enhancements_doc/Enhancement-859.md). `ft_numparse` reads the scale
factor after the exponent, and the two go to `INPdecimal` as one exact decimal: the netlist's
value to the bit.*

| text | element value, B-source | `let` |
|---|---|---|
| `1.5e2u` | 1.5e-4 | 150 |
| `1e3meg` | 1e9 | 1000 |
| `1e-3k` | 1 | 0.001 |

The netlist parsers apply the exponent and the suffix, and the front end reads the exponent and
ignores the rest. A control script that computes a value from a netlist's text gets a
different number, silently.

<a id="f5"></a>
## F5 — the ac solve loses digits on inductive networks at low frequency

*Fixed in [E-860](../../enhancements_doc/Enhancement-860.md). After each ac solve the residual
gives the componentwise backward error. Where that is above rounding, one step of iterative
refinement with the same factors restores the digits; a point solved well keeps its bits.
Flagged networks went from 22 under Sparse and 5 under KLU to 1 under each, and that one is
off by 1.5e-9 under both alike, as it was before. Its cost is one pass over the matrix per
frequency: +6 to +25 % on circuits whose devices load almost nothing.*

At a few hertz, a 1 nH inductor's branch row carries jωL ~ 1e-8 beside entries of order 1. The
factorization accepts a pivot down to `pivrel` (1e-3) of its column's largest entry, and Sparse
orders the matrix once, at the first frequency. On 300 inductor-heavy networks swept from
0.1–10 Hz:

| | networks over 1e-9 × cond | worst error | worst condition |
|---|---|---|---|
| Sparse | 22 | 3.4e-6 | 5 |
| KLU | 5 | 2.0e-7 | 5 |

On these matrices any backward-stable solve gives 1e-15. With `.option pivrel=1` the same
networks come out to between 2e-16 and 7e-16 under both solvers (seed 5025 under Sparse,
3.5e-12). In the random networks of the first ac run, 2 of 300 lost digits this way, both
under Sparse. One step of iterative refinement after the solve would restore them at the cost
of a residual and a back-substitution.

<a id="f6"></a>
## F6 — dc sensitivities to a resistance are low by 1e-6

*Fixed in [E-861](../../enhancements_doc/Enhancement-861.md). The step is central, p + δ against
p − δ over 2δ, where the parameter is not zero, with the same number of loads. dV(4)/dR1 comes
out 1.6e-11 from the analytic value, in dc and ac alike.*

```spice
vin 1 0 dc 1
r1 1 2 1k
r2 2 0 2k
e1 3 0 2 0 5
r3 3 4 500
r4 4 0 1k
.control
sens v(4)
```

dV(4)/dR1 is −7.4074074e-4; ngspice gives −7.40740000e-4. `e1_gain` is right to 4e-11.
`cktsens.c` perturbs every parameter by `Sens_Delta` = 1e-6 of its value and divides the change
in the device's stamp by that step. A gain enters the stamp linearly, so its quotient is exact.
A resistance enters as 1/R, and (1/(R+δ) − 1/R)/δ = −1/(R(R+δ)), low by the factor 1/(1+1e-6).
Every sensitivity to a resistance checked, 157 in 40 networks, is off by exactly that factor.
The median error of the others is 3e-11, and over all 300 networks no sensitivity is further
off. A central difference would make it 1e-12.

<a id="f7"></a>
## F7 — three values of kT/q

```verilog
V(a) <+ $vt(300.15);
V(b) <+ `P_K * 300.15 / `P_Q;
```

`v(b)/v(a)` − 1 = 1.05e-6. The compiler's `$vt` uses the 2019 exact SI constants. Its comment
says the shipped `constants.vams` defaults `P_K` and `P_Q` to the same set, but the default branch
of that header is NIST 1998, as [Enhancement-519](../../enhancements_doc/Enhancement-519.md) chose
for backward compatibility. ngspice's own constants are CODATA 2014: `boltz*300.15/echarge` is
3.4e-7 below `$vt`.

In family E, Verilog-A resistors with `white_noise(4*`P_K*$temperature/r)` put the output
noise of 102 networks above the all-built-in run's, by up to 6.4e-7 in amplitude. That is
1.3e-6 in power, the ratio of the two Boltzmann constants.

<a id="f8"></a>
## F8 — `let` refuses tan(0)

`let b = tan(0)` fails "argument out of range for tan"; `tan(0.5)` is fine. `d_tan` in
`cmath1.c` checks `tan(x) != 0`, which only refuses a valid result. The `.param` and B-source
`tan(0)` are 0.

<a id="f9"></a>
## F9 — complex `%` refuses a real divisor

```
ac lin 2 1k 2k
let a = v(1) % 2
```

This fails "argument out of range for mod". Complex `%` takes the real and imaginary parts
separately and checks that both of the divisor's are nonzero. A real divisor, promoted to
complex, has an imaginary part of 0. `v(1) % (2+j(1))` evaluates.

<a id="f10"></a>
## F10 — power associativity and the precedence table

| | `.param` | B-source | `let` |
|---|---|---|---|
| `2^3^2` | 64 | 64 | 512 |
| `2^0.5^2` | 2 | 2 | 1.189 |
| `-2^2` | −4 | −4 | −4 |

The manual (§2.11) says equal-precedence binary operators evaluate left to right, which is 64.
`let` evaluates right to left, as Verilog-A, C's `pow` chains and mathematics do. The same
table gives unary minus precedence 1 and `**` precedence 2, which would make `-2^2` = 4; the
three parsers agree on −4, so the table is what is wrong there.

<a id="f11"></a>
## F11 — a pz plot's names in `write` and `print all`

`display` after `pz` shows `pole(1)`. `write` of the plot names its variables `pole(1)`,
`v(pole(2))`, `v(zero(1))`. When the plot holds one pole, it writes it twice, as `pole(1)` and
`v(all)`. `print all` on that plot prints `all = -1.5e+06,0`. A rawfile written from a pz plot
does not load back under its own names.

## Not defects

- **`pwr` has two definitions,** both in the manual. In a `.param` it is pow(|x|, y), so
  `pwr(-2,2)` is 4. In a B-source it is sign(x)·|x|^y, so the same text is −4. Both parsers do
  what their section says.
- **B-source guards are silent by design:** `1/0` is 1e32, `0/0` is 0, `exp(800)` is 1e99,
  `ln(0)` is −1e99, and `(-8)^(1/3)` is 2.
- **Default-tolerance transients of picofarad networks** were 25 % to 34 % off a tight
  reference in E and H, for built-in and Verilog-A elements alike. This is campaign 2's
  `chgtol` note again. Built-in and Verilog-A runs agree to 6e-4 at tight tolerances.

## Verified clean

- **A, ac:** 300 networks and 10 454 points under both solvers match the exact solve within
  1e-15 × condition, apart from F5's two. Sparse and KLU agree.
- **B, expressions:** every one of the 4 000 random expressions that a `.param` accepts gives
  the same value through all three parsers, under both solvers. Python agrees too, once its own
  reading of `8.2t` as 8.2×1e12 is replaced by the correctly rounded 8.2e12 that ngspice uses.
  `nint` rounds half to even everywhere, as documented.
- **C, tf and pz:** the gain, input and output resistance of 300 networks are exact under both
  solvers; flags were rounding at outputs held at 0 V. 2 042 roots match, apart from F1.
- **D, nonlinear:** 200 networks under Sparse and KLU converge or fail together. Their op, dc
  sweep and transient agree within 1e-5 and 1e-3 of range.
- **E, OSDI twins:** op and ac of 150 networks with 1 355 twins agree with the built-in
  networks to 1e-12 and 1e-10, and noise to F7's 6.3e-7.
- **F, sessions:** all 840 sequences equal their fresh-session runs to 1e-9, under both
  solvers. That includes `alter` followed by `reset`, `set temp` and back, a transient after
  a transient, and every analysis after `pz`, `disto`, `sens` and `noise`.
- **G, stress:** 8 946 points over 15 decades of element values are within the
  condition-number bound under both solvers. Sparse and KLU differ only where that bound is
  above 1e-9.
- **H, collapse:** 561 collapsed branches in 300 circuits give the built-in network's op and
  ac to 1e-9 under both solvers. The transient agrees within tolerance.
