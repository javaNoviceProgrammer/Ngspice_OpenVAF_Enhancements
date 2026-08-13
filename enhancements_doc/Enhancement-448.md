# Enhancement-448 — a node named after a constant

ngspice keeps a permanent `const` plot holding twelve vectors — `c`, `e`, `i`,
`pi`, `kelvin`, `boltz`, `echarge`, `planck`, `TRUE`, `FALSE`, `yes` and `no` —
and `vec_get()` falls back to it whenever the current plot has no vector of that
name. That fallback is how a bare `pi` resolves, and it must stay.

It also meant that a **node** named after one of those twelve was answered with
the constant instead. Three distinct failures came out of it, and the third has
nothing to do with constants at all.

## `v(c)` answered with the speed of light

`v(X)` asks for a node voltage. A constant is never one. But the name was
resolved before the context was considered, so a node that had been renamed —
or simply mistyped — was answered rather than refused:

```
circuit has a node `coll`; the deck asks for v(c)

print v(c)                 2.9979245800e+08
print v(nosuch)            Error: no such vector nosuch
```

The second line is what the first should have done. Worse, **the eleven other
names are more dangerous than the speed of light, because they look like
results**:

```
v(no)       0.0000000000e+00
v(i)        1.0000000000e+00
v(yes)      1.0000000000e+00
v(TRUE)     1.0000000000e+00
v(kelvin)  -2.7315000000e+02
v(e)        2.7182818285e+00
```

A flat 0.0 is indistinguishable from a grounded node.

### It defeated an existing guard

[E-431](Enhancement-431.md) refuses a `sweep -output` expression that never
resolves. That refusal works — and the constant walked straight through it,
because the name *did* resolve:

```
sweep R1 1k 5k 2k -output vo=v(nosuch)
    Error: sweep -output v(nosuch) never resolved -- no such vector;
           that curve is not recorded.

sweep R1 1k 5k 2k -output vo=v(c)
    0   2.9979245800e+08
    1   2.9979245800e+08         <- drawn as a curve
    2   2.9979245800e+08
```

In a sweep the output *is* a curve you plot against the knob, so a flat line
reads as a legitimate finding: "this output does not depend on the knob."

A node context no longer accepts a constant-plot binding. `v(c)` now says
`no such vector c`, and E-431's refusal fires exactly as it does for any other
bad name. The related forms — `v(c,0)`, `vm/vp/vr/vi/vdb(c)`, `i(c)`,
`mag(v(c))` — were checked and were already refusing; `v` is the only entry in
the function table with a null handler, which is why it alone had the hole.

## A bus bit named `c[0]` was unreachable

`.option autobus` ([E-444](Enhancement-444.md)) builds the node names `c[0]` …
`c[4]` for a Verilog-A bus port called `c`. Those nodes were created correctly
and the circuit solved correctly around them — and not one of them could be
named:

```
display              c[0] : voltage, real, 1 long
print all            c[0] = 5.0000000000e-01      <- correct, and printed
print c[0]           Error: indexing a scalar (c)
print v(c[0])        Error: bad v() syntax
```

The five-bit ladder from E-444's own suite, with the bus renamed from `a` to
`c`, printed **nothing at all**.

[E-224](Enhancement-224.md) already preferred the literal name `a[0]` over
"index 0 of a vector `a`" — but only when the base was an *unresolved*,
zero-length placeholder. For all twelve constant names a vector called `c`
always exists, so the literal path was never tried. The gate is now the literal
vector's own existence: if the current plot holds a vector spelled exactly
`c[0]`, that is what `c[0]` means.

## The silent one, which needs no constant

The same gate failed whenever the base resolved to a **longer** vector — which
in a transient run is every node. A circuit holding both a scalar node `q` and
a bus bit `q[0]`:

```
tran 1u 5u

print q[0]        7.5000000000e-01     a SCALAR: node q at t=0        SILENT
print "q[0]"      59-row waveform      the real node q[0]
```

You get the wrong node's first sample, as a scalar, with no diagnostic. In an
`op` run the same expression errors instead, because every vector is length-1 —
so the failure mode flipped with the analysis type. This is the case that
argues the fix is about bracketed names generally, not about the constant plot.

## A bare name still resolves to the constant

With the two above fixed, `v(c)` and `c[0]` can no longer reach the fallback at
all. What is left is a **bare** `c`, which is genuinely ambiguous — the constant
plot exists precisely so that bare `pi` works. It still resolves to the
constant, but no longer in silence when the name also exists as a vector
somewhere else, i.e. only when the user plausibly meant that one:

```
op
setplot new
print c      Warning: 'c' resolved to the built-in constant, but plot op1
                      has a vector of that name; write op1.c for it.
             2.9979245800e+08
```

A deck with no such node — every ordinary use of a constant — stays silent.

## One rule, four places

The bracketed-name rule was re-derived in four separate places, each with the
same too-narrow gate: `checkvalid()` and `PP_mksnode()` in `parse.c`, and
`op_ind()` and `apply_func()` in `evaluate.c`.
[E-408](Enhancement-408.md) recorded what happens when copies of one rule drift
apart — `@dev[param]` was split across four commands and behaved differently in
each. It is now a single `e448_literal_index()` in `evaluate.c`, declared in
`evaluate.h` so `parse.c` shares it rather than re-deriving it.

## A deliberate change of meaning

Where **both** a vector `x` and a vector literally named `x[0]` exist, `x[0]`
now means the literal one; it previously meant element 0 of `x`. That is the
only case in which a working expression changes meaning, and the reading it
replaces is the silent-wrong-answer case above. Indexing in that situation
needs a temporary, and the warning says so:

```
Warning: 'q[0]' is itself a vector, so it is read as that vector rather than
         as element 0 of 'q'; copy 'q' to a temporary to index it.
```

Ordinary indexing is untouched, because nothing is named `myvec[3]`.
[E-433](Enhancement-433.md)'s quoting (`"c[0]"`) keeps working and remains the
way to be explicit.

## One change made and withdrawn

A hook was added to `checkvalid()` so `v(c)` would be reported once rather than
once per sweep point, on the evidence that a 21-point sweep printed 22 copies of
the error where `-output v(nosuch)` printed one. **That evidence was an artifact
of the probe.** The two paths emit different wordings — `no such vector` versus
`is not available or has zero length` — and the filter matched only the first.
Counted properly both emit 23 lines: the repetition is pre-existing `sweep`
behaviour for any unresolved output and has nothing to do with this change. The
hook was reverted; it would have added a fifth place that knows about `v()` for
no benefit.

## Verification

A baseline was captured on the **pre-fix** binary before any source was
touched, so the controls are measured rather than assumed: all six defects
reproduced there, and all thirteen controls — the constants, numeric node names
(`v(1)`, `v(2)`), ordinary vector indexing, and E-224's array nodes — already
held.

**`examples/constname_examples` — 57/57, both solvers.** Every fix narrows what
a name may mean, so each is paired with a control that must not move:

* all nine spot-checked constants still read their values, bare, inside an
  expression, after an analysis, and with no analysis at all
* `v(c)` reads the **node** when one exists, and is refused for all twelve
  names when none does
* `-output v(c)` and `-output v(no)` are refused, while a real node named `c`
  still sweeps to 0.5 / 0.75 / 0.833
* all twelve `<const>[0]` bus bits read through both `c[0]` and `v(c[0])`,
  while E-224's ordinary `q[0]` and E-433's quoted `"c[0]"` still work
* the `q` / `q[0]` circuit reads the bus bit in both `op` and `tran` **and
  reports the ambiguity**, while ordinary `z[3]` indexing is unchanged and
  silent
* `v(1)` and `v(2)` still read numeric nodes
* the bare-name warning fires with the node in another plot and stays silent
  for an ordinary node read, an ordinary constant read, and an unrelated
  constant

The decisive end-to-end check is E-444's own five-bit ladder run twice: with
the bus named `a` and with it named `c`. **The two now read bit-identical.**

**Full regression 360/360**, both solvers.
