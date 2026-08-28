# Enhancement-497 — constraints the documentation states and the code did not check

```
python3 verify_argcheck.py
```

52 checks, a few seconds. **33/52** against the pre-fix binary — **19** checks
discriminate.

## What it is

Round 56 mined the manual for stated numeric constraints and asked, of each,
whether anything enforces it. Three of these five came straight out of

```
pdftotext ngspice-manual.pdf | grep -E "must be|should be"
```

## 1. `disto`'s f2overf1 ratio

The manual: *"it should be a real number between (and not equal to) 0.0 and
1.0."* Nothing checked it, and the value **moves the answer**:

| ratio | 2F1−F2 product | |
|---|---|---|
| 0.5 | 1.711 | legal |
| 1 | 1.630 | F2 = F1, so "IM: f1−f2" is at DC |
| 0 | 1.695 | second tone at DC |
| 1.5 | 1.477 | F2 > F1 — well posed, still allowed |
| −0.5 | 1.580 | negative frequency |

Both neighbouring cases in the **same switch** (`D_START`, `D_STOP`) test their
value and return `E_PARMVAL`. Refused rather than clamped: the ratio *is* the
experiment being asked for, and any substitute would answer a different question
without saying so.

**Narrower than the manual.** The first version refused everything outside
(0,1), and [E-255](../../enhancements_doc/Enhancement-255.md)'s suite caught it:
that suite measures IM3 at f1 = 1.0 GHz, **f2 = 1.3 GHz** and proves the answer
machine-exact against an independent QPSS harmonic-balance engine. F2 above F1
is well posed. Only `<= 0` (second tone at DC or negative) and `== 1` (F1−F2
would be DC) are refused.

## 2. `setseed` and a fractional seed

`%d` stops at the first character it cannot use, so `2.5` scanned as **2**.
Every other bad spelling is named (`0`, `-3`, `abc`), and the sibling command
`repeat` names a fractional count outright.

## 3. `s_xfer` indexed `int_ic` by the wrong array's size

`PARAM(int_ic[den_size - 2 - i])` — `den_size` being `PARAM_SIZE(den_coeff)` —
with nothing consulting `PARAM_SIZE(int_ic)`, though the manual states the
relationship. Too short and the unreached initial conditions read zero, taking
v(out) at 10 µs from **7.00005 to 4.99995e-05**; too long and the surplus was
never looked at.

## 4. The oscillator family went silently dead

`sine`, `square`, `triangle` and `oneshot` detected a control/frequency array
mismatch, announced it, and returned **without setting an output** — on every
evaluation:

| | before | after |
|---|---|---|
| exit code | 0 | 1 |
| output | held at zero | run stops |
| message blocks over 2 ms | **2025** | 1 |

It scales with the run — a 1 s transient printed about a million lines. This is
the shape [E-491](../../enhancements_doc/Enhancement-491.md) fixed in
`s_xfer`'s `cfunc.mod` and named there: two arrays of different length cannot
become the same length at a later timepoint, so say it once and stop.

## 5. A duplicate `.param` was the only one of its family to pass in silence

```
.func   f(x)   redefined  ->  "is defined more than once"   (E-491)
.model  m      redefined  ->  "is already defined; keeping ..."
.subckt s      redefined  ->  "redefinition of .subckt s, ignored"
.param  a      redefined  ->  nothing at all
```

and it resolves the **other way** from two of them — `.model` and `.subckt` keep
the *first*, `.param` takes the *last* — so two included files that each set
`vdd` agree or disagree purely by **include order**, and a `.param` written in
the deck is silently displaced by a library included after it.

Which value wins is **not** changed; it is only made audible. Scoped to
top-level cards, because a subcircuit's own parameters are legitimately
redefined once per instance.

## What must not move

Every meaningful disto ratio (including above 1) and single-tone `disto`; the neighbouring `disto` argument
checks; `setseed` with an integer, with surrounding blanks, and its existing
messages for `0`/`-3`/`abc`; `s_xfer` with a correct `int_ic`, with none at all,
and E-491's num>den guard firing first; a matching `cntl_array`/`freq_array`
pair on all three oscillators; a single `.param`, two names on one card, a
subcircuit's own parameters, and the `.func`/`.model`/`.subckt` messages.
