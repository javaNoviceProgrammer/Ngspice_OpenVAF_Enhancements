# Enhancement-394 — the subcircuit multiplier, the instance temperature, and four more ngspice/OSDI plumbing defects

Six defects from a one-hour hunt aimed at **ngspice + OSDI** (previous rounds
targeted the compiler). Five of the six are one shape: **it works for a built-in
device and silently does not for an OSDI (compiled Verilog-A) one**. The sixth
turned out not to be OSDI-specific at all.

## 1. The subcircuit multiplier never reached an OSDI device

`X1 a 0 sub m=3` scales a built-in resistor or diode inside `sub` exactly. An
OSDI device in the same position contributed **1×** — in DC, AC, transient,
thermal noise, flicker noise, charge and S-parameters alike. `$mfactor` read
inside the model was always the device's own `m`, never multiplied by any
enclosing `X`, at any nesting depth.

The cause is one character. `inp_fix_subckt_multiplier` appends ` m={m}` to each
device line inside a multiplied subcircuit, skipping lines whose first letter
names a device with no multiplier:

```c
if (strchr("*vehaknopstuwy", curr_line[0]))
    continue;
```

`'n'` is in that list, and **`N` is the OSDI dispatcher**. PDKs wrap compact
models in multiplied subcircuits, so this under-counted device area with no
diagnostic of any kind.

`N` also hosts the native **n-port**, which genuinely has no multiplier and
which *errored* on an unexpected `m=`. Removing `'n'` from the skip list would
have turned a silent no-multiply into a hard parse error there, so `nport` now
accepts `m` and reports when it is not 1. That is deliberately not a silent
acceptance: the multiplier was being dropped for n-ports too, which is the same
defect class this release exists to fix, and it is now visible. Applying a real
multiplier to the n-port would mean scaling a stateful convolution and its
history terms; no finding here concerns that device, and a change of that shape
does not belong in this release.

## 2. Nested subcircuit multipliers did not compound

Found while characterising (1), and **not OSDI-specific — built-in devices were
equally affected**. Only the outermost `m=` survived:

| nesting | gave | should give |
| --- | --- | --- |
| outer 2 × inner 3 | 2× | 6× |
| outer 3 × inner 2 | 3× | 6× |
| 2 × 3 × 5 | 2× | 30× |

The append path multiplied an existing `m=` **only in HSPICE compatibility
mode**; everywhere else it appended a second ` m={m}`, which won and discarded
the inner value. Multiplying is the SPICE meaning and is exactly what the HSPICE
path already did, so that logic now runs unconditionally.

A subcircuit that *declares* `m` as a parameter is a separate case and was
always right: `X`'s `m=` binds the parameter and must not additionally multiply.
That is pinned in the accept half.

## 3. Instance `temp=` was not converted from Celsius to Kelvin

Every built-in adds `CONSTCtoK` when the parameter is set — `dioparam.c` does
`DIOtemp = value->rValue + CONSTCtoK` — and ngspice's own OSDI code acknowledges
the same convention where it hands `tnom` to the model as
`CKTnomTemp - CONSTCtoK`. The OSDI path stored the raw number and then used it
directly as the Kelvin device temperature.

| | `$temperature` | `$vt` |
| --- | --- | --- |
| `temp=75` | 75.0 | 6.5 mV |
| correct | 348.15 | 30.0 mV |

On a Verilog-A diode that is **−2.5×10¹⁶ A where the correct answer is
−4.85×10⁻⁷ A**. `temp=0` made `$vt` exactly zero, so `limexp(V/$vt)` divided by
zero and the operating point failed outright; `temp=-40` produced a negative
absolute temperature and a negative thermal voltage. Nothing warned.

`temp` also **stacked** with `dtemp` (`temp=75 dtemp=10` meaning 85). It
overrides now, as it does for every built-in — `restemp.c` forces `dtemp = 0`
and prints *"Instance temperature specified, dtemp ignored"*, which is now the
message an OSDI instance prints too, with the same silence during sensitivity
analysis.

`.temp`, `.option temp`, `dtemp` and temperature sweeps were all correct
throughout; only this one path was raw.

## 4. `.option scale` never reached an OSDI model

Each built-in applies it inside its own parameter setter (`b3par.c` and friends
call `cp_getvar("scale")`). Nothing scales an OSDI instance parameter, and
nothing can: the OSDI ABI carries no units, so ngspice cannot know which
parameters are lengths.

The Verilog-A way to receive it is `$simparam("scale")` — and real models ask
for it. The **EKV model in this project's own `VA_TEST` corpus** has
`` `define SIMPARSCAL $simparam("scale",1.0) ``. ngspice's OSDI simparam table
held ten entries and `scale` was not among them, so the model silently used
`1.0` while a built-in MOSFET in the same netlist scaled from `l=2` to `2e-6`.
`scale` is now served, and there is no double-application risk precisely because
ngspice never touches an OSDI parameter itself.

`shrink`, `imax` and `rthresh` — which the same EKV macros also request — are
deliberately **not** added: ngspice has no such option, so the honest outcome is
the model's own `$simparam` default rather than an invented value.

## 5. `.options savecurrents` produced nothing for OSDI devices

`@r1[i]` appeared for a built-in resistor and the compact model beside it
produced no current vector at all. `@n1[i]` did not exist, so the only way to
see a compact model's terminal current was to edit the model and expose it as an
operating-point variable.

Every OSDI instance now answers to `i_<terminal>`, and a two-terminal one also to
the bare `i` that R/C/L use. The value is the device's own stamp into that node's
KCL row — the resistive residual, plus in a transient the integrated charge
derivative that `OSDIload` places in the state vector — so it is exact rather
than a finite difference. Verified three ways: equal-and-opposite on a
two-terminal device, KCL summing to 3×10⁻¹⁶ on a three-terminal one, and
`C·dV/dt` during a transient ramp.

`.options savecurrents` emits `.save @dev[i]` for `N` lines. **Scope boundary,
stated rather than hidden:** that pass is a textual pre-pass over the deck, and a
model's terminal *names* are not knowable at that point, so devices with more
than two terminals are not auto-saved. They are read per terminal by name
(`.save @n1[i_d]`), which is what the per-terminal parameters exist for.

## 6. `$simparam$str("analysis_name")` contradicted `analysis()`

[E-53](Enhancement-53.md) taught the `ANALYSIS_*` flags to consult the running
job, so that an AC job's operating-point phase reports `ac`. The string channel
was left on the old CKTmode-only derivation, and `OSDIfinalStep` carried a
**third** derivation of its own that tested `MODEAC` without `MODEINITSMSIG`.

Two contradictions followed, inside a single model evaluation:

- a plain `op` reported `name=ac` while `analysis("ac")` was false;
- an AC job's op phase reported `name=dc` while `analysis("ac")` was true.

A model gating on the string therefore behaved differently from one gating on
`analysis()` — and the in-source comment claiming the string was "derived from
CKTmode with the same convention as analysis()" had quietly become false.

### The mistake worth recording

The obvious repair is to make the other two channels match `OSDIload`, since it
is the one E-53 updated. That is wrong, and the existing
`examples/finalstep_examples` suite said so immediately: it pins that
ac-qualified events stay **silent** during a plain `op`, and propagating
`OSDIload`'s derivation made `final_ac` fire there.

`OSDIload` was in fact the odd one out. It set `CALC_REACT_JACOBIAN` and
`ANALYSIS_AC` together from `MODEAC | MODEINITSMSIG` — but those are different
questions. The reactive Jacobian genuinely *is* needed during `MODEINITSMSIG`,
because that pass computes small-signal capacitances after a DC solution;
`ANALYSIS_AC` is a **name**, and a plain `op` is not an AC analysis.

So the two were separated: the reactive bit still follows
`MODEAC | MODEINITSMSIG`, while the name bit — in all three channels — follows
`MODEAC` plus E-53's job consultation for an AC/noise job's operating-point
phase. `OSDIfinalStep` reverts to what it had, which was right all along. A
plain `op` now reports exactly one phase, `dc`, and nothing claims `ac` anywhere
in it.

**A suite that pins behaviour you are about to "unify" is the cheapest possible
review.** The first attempt looked more principled and was less correct.

## Verification

`examples/osdiplumb_examples` — **45/45 fixed, 14/45 against the shipped
binary**. Thirty-one checks pin real defects.

Every OSDI check carries a **built-in control in the same netlist**, because
"the OSDI number changed" is not evidence — "the OSDI number now equals what the
equivalent built-in network gives" is.

The accept half matters more than usual here: (1) and (2) change how *every*
multiplied subcircuit is expanded, built-in devices included, so the suite pins
a single level, an explicit inner `m`, a fractional `m`, the unmultiplied case,
and the subcircuit that declares `m` as a parameter and must not double-apply.

Beyond the suite: full regression **318/318**.
