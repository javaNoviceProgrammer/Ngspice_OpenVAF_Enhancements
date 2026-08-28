# Enhancement-497 — constraints the documentation states and the code did not check

**Files:** `src/spicelib/analysis/dsetparm.c`, `src/spicelib/analysis/nsetparm.c`,
`src/maths/misc/randnumb.c`, `src/frontend/inpcom.c`, and five XSPICE models —
`s_xfer`, `sine`, `square`, `triangle`, `oneshot`.

**Suite:** `examples/argcheck_examples/` — 51 checks.

## Why

Round 56 tried a technique worth keeping: mine the manual for stated numeric
constraints, then ask of each whether anything enforces it.

```
pdftotext ngspice-manual.pdf | grep -E "must be|should be"
```

Three of the five findings came straight out of that one command.

## 1. `disto`'s f2overf1 ratio was unvalidated

> If the optional f2overf1 parameter is specified, **it should be a real number
> between (and not equal to) 0.0 and 1.0**

Nothing checked it, and it is not decorative — the ratio sets the second tone, so
it moves the answer. On a reactive circuit, the 2F1−F2 product:

| ratio | result | what it means |
|---|---|---|
| 0.5 | 1.711 | legal |
| **1** | 1.630 | F2 = F1, so the plot still labelled *"IM: f1−f2"* holds a product at **DC** |
| **0** | 1.695 | the second tone is at DC |
| 1.5 | 1.477 | F2 > F1 — well posed, see below |
| **−0.5** | 1.580 | the second tone is at a **negative frequency** |

Every one accepted in silence, and the numbers look ordinary either way — which
is what makes the silence expensive.

**Both neighbouring cases in the same switch** already do this properly:
`D_START` and `D_STOP` each test `<= 0.0`, set `errMsg` and return `E_PARMVAL`.
`D_F2OVRF1` was a bare `job->Df2ovrF1 = value->rValue;`. The noise analysis
validates every analogous argument of its own.

**Refused rather than clamped.** There is no defensible value to clamp to: the
ratio *is* the experiment the author is asking for, and any substitute would
answer a different question without saying so.

**Narrower than the manual, and deliberately so.** The first version of this
guard took the manual at its word and refused everything outside (0,1).
Enhancement-255's suite caught that immediately: it measures the two-tone IM3 at
f1 = 1.0 GHz and **f2 = 1.3 GHz** — a ratio of 1.3 — and proves the result
machine-exact against an independent QPSS harmonic-balance engine. F2 above F1
leaves all three products at distinct non-zero frequencies and is perfectly well
posed; keeping F2 below F1 is a convention, not a requirement, and a working
verified deck is better evidence of that than the sentence in the manual.

So what is refused is only what has no meaning:

| ratio | why |
|---|---|
| `<= 0` | the second tone would sit at DC or at a negative frequency |
| `== 1` | F2 = F1, so F1−F2 is DC and 2F1−F2 is F1 — the three plots are then not intermodulation products at all, though they are still labelled as such |

A ratio above 1, including E-255's 1.3, runs exactly as before.

## 2. `setseed` silently truncated a fractional seed

`%d` stops at the first character it cannot use, so `setseed 2.5` scanned as
**2** and the run used seed 2. Every other bad spelling is named — *"Cannot use
0 / -3 / abc as seed!"* — and the sibling command `repeat` names a fractional
count outright: *"bad repeat argument 3.7"*. This was the one way to be wrong
quietly. The manual asks for "an integer greater than 0"; the whole token must
now be that integer, with surrounding blanks still fine.

## 3. `s_xfer` indexed `int_ic` by the wrong array's size

The initialisation loop reads

```c
PARAM(int_ic[den_size - 2 - i])      /* den_size = PARAM_SIZE(den_coeff) */
```

and **nothing anywhere consults `PARAM_SIZE(int_ic)`**, though the manual states
that int_ic "must be of size one less as the array of values specified for
den_coeff". Too short, and the initial conditions the array does not reach read
as zero — v(out) at 10 µs went from **7.00005 to 4.99995e-05** on a second-order
section. Too long, and the surplus was never looked at. Either way, silence.

Checked once at setup and refused the way E-491's two guards in the same file
refuse: the size cannot become right at a later timepoint.

## 4. The oscillator family went silently dead

`sine`, `square`, `triangle` and `oneshot`:

```c
if (cntl_size != freq_size) { cm_message_send(array_error); return; }
```

announced the fault and returned **without setting an output** — on every
evaluation.

| | before | after |
|---|---|---|
| exit code | **0** | 1 |
| the source | held at **zero** all run | run stops |
| message blocks over 2 ms | **2025** | 1 |

and it scales with the run: a 1 s transient printed roughly a million lines.

This is precisely the shape **Enhancement-491 fixed in `s_xfer`'s `cfunc.mod`**,
whose comment already spelled out the reasoning — *"say it once and stop, the way
file_source does when its file will not open"*. Four models were left doing the
old thing.

`d_osc` and `d_pwm` perform the same check **inside their `INIT` block**, so they
already say it once; they are deliberately untouched.

## 5. A duplicate `.param` was the only one of its family to pass in silence

```
.func   f(x)   redefined  ->  "is defined more than once"        (E-491)
.model  m      redefined  ->  "is already defined; keeping ..."
.subckt s      redefined  ->  "redefinition of .subckt s, ignored"
.param  a      redefined  ->  nothing at all
```

and it resolves the **other way** from two of them: `.model` and `.subckt` keep
the **first** definition, `.param` takes the **last**. So two included files that
each set `vdd` agree or disagree purely by **include order**, and a `.param`
written in the deck is silently displaced by a library included after it — both
measured.

**Which value wins is not changed.** Decks depend on last-wins; it is only made
audible, exactly as E-491 did for `.func`. Scoped to **top-level cards** by the
same `.subckt` nesting count that already governs the `.func` scan, because a
subcircuit's own parameters are legitimately redefined once per instance — a
check the suite makes three ways.

## Also fixed, with no demonstrated consequence

`dsetparm.c`'s `D_STOP` and `nsetparm.c`'s `N_STOP` each reset the **start**
frequency field when it was the **stop** frequency that was refused. Both return
`E_PARMVAL` before either field is read, so nothing observable followed — but the
line said the opposite of what it did.

## What must not move

* **Every meaningful disto ratio** — 0.001 through 0.999, and **above 1**
  including E-255's 1.3 — and **single-tone `disto`**, plus the neighbouring
  points/start/stop checks.
* **`setseed`** with an integer, with surrounding blanks, and its existing
  messages for `0`, `-3` and `abc`.
* **`s_xfer`** with a correct `int_ic`, with none at all, and E-491's num>den
  guard still firing first.
* **A matching `cntl_array`/`freq_array`** on all three oscillators.
* **A single `.param`**, two names on one card, a subcircuit's own parameters
  (three shapes), and the `.func`/`.model`/`.subckt` messages.

## Verification

```
python3 examples/argcheck_examples/verify_argcheck.py   # 52/52
python3 examples/run_regression.py                      # 411/411
```

**33/52** against the pre-fix binary, so **19 of 52 checks discriminate**. The
other thirty-three are the controls above — most importantly that a subcircuit's own
parameters are not mistaken for duplicates, which is the way this change could
most easily have gone wrong.
