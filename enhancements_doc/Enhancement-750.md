# Enhancement-750: the vector fit's error is measured against the block, not against its negligible elements — and its order climb goes past 24 poles, stops after two flat steps, names its cap, takes `-maxpoles` and `-order`, traces itself under `PRE_SNP_DEBUG`, and both Touchstone readers accept a line of any length

**Scope:** found while timing the two `pre_snp` backends on a 16-port bus of
eight coupled lines, after the Touchstone-import hunt. `src/frontend/snp2va.c`
(the error measure, the climb, the knee, the cap and the flags, the trace,
the growable line reader), `src/frontend/snp2va.h`, `src/frontend/com_presnp.c`
(`-maxpoles <N>`, `-order <N>`, the usage), `src/frontend/commands.c` (the
help), `src/frontend/postcoms.c` (`rdsnp`'s growable line reader),
`examples/presnp_examples/` (five checks, the writer's precision argument),
`examples/touchstone_examples/` (one check). **ngspice only.** The fit's
algorithm, both emitters and the native device are untouched.

**Suites:** [`presnp_examples`](../examples/presnp_examples/) 31 of 31 (26
of 31 on the E-749 binary), [`touchstone_examples`](../examples/touchstone_examples/)
27 of 27 per solver, both solvers (26 of 27 on the E-749 binary); `lowrank`,
`nport_native`, `snpfuzz` unchanged; full sweep 532 of 532.

## What was wrong

The bus — eight channels, each a series R-L pair per half segment, coupled
through capacitors between neighbouring midpoints — was refused by E-745 at
23 percent rms error. The first reading was the order cap: the climb went a
pole pair at a time to 12 pairs and stopped. Raising the cap did nothing: the
error sat at exactly 0.2334 from 8 poles to 24 and rose to 0.88 above, over
55 seconds. A plateau that exact is not an order problem.

The fit's error was the worst element's rms error *relative to that
element's own size*. The bus's admittance between its two farthest channels
is 4e-11 of its diagonal — seven coupling capacitors away — and the fit's
absolute error on it, tiny in every sense that matters, was 23 percent of
it. The block was fitted to 1.5e-8 of its largest element at 16 poles and
refused as garbage.

Three smaller things sat beside it. The knee rule ended the climb on one
flat step and handed back the previous order; the bus gives the same error
at 6 poles as at 4 and drops three decades at 8, so the climb stopped at 4.
A fit that could not converge climbed to whatever cap it had. And both
readers took a line into a fixed 4 KB buffer: a 16-port frame written on
one line is 513 numbers, over 8 KB, and a number cut in two at the boundary
made a wrong count or a wrong value in silence.

## What changed

**The measure.** Each element's rms error is relative to the larger of its
own size and a thousandth of the largest element's. An element that matters
is still held to its own scale; a negligible one no longer decides. The
acceptance tolerance moved from 1e-3 to 1e-4 on that measure, since the
negligible elements had been the reason a fit went on past 1e-3.

**The climb.** One pair at a time to 12, then a fifth per step, to a cap of
80 poles by default and never more than the frequency points support. The
knee needs two flat steps in a row, measured against the best so far, near
the floor or anywhere past 12 pairs, and returns the best fit rather than
the previous order. A fit that reaches the cap without converging says so
in its status line and in E-745's refusal, with `-maxpoles` named.

**The flags.** `pre_snp -maxpoles <N>` sets the cap for one command;
`-order <N>` pins the pole count (rounded up to a pair), as `snp2va.py`'s
`--order` does; a bad value is refused naming the flag and the default.
`PRE_SNP_DEBUG=1` in the environment prints one line per order tried, with
its error, the way the fit was diagnosed here.

**The readers.** `parse_touchstone` and `rdsnp` read a line of any length
into a growable buffer.

On the bus the climb now reads 2 → 7.8e-2, 4 → 1.0e-3, 6 → 1.0e-3, 8 →
1.5e-5, converges, and the block matches its built-in twin. On a random
file it stops at 30 poles instead of climbing to the cap. Every fit the
suites had converges at the same order as before.

**What the file's precision does.** Written with eight significant digits
the same bus fits to 1e-3 and no better, with ten to 1.5e-5: the S-to-Y
conversion of a near-transparent line amplifies the file's rounding by the
inverse of I + S, whose small eigenvalue is 1 − |S21|. The measure now shows
that limit instead of hiding it under a negligible element's noise.

## Verification

`presnp`: the bus (its file written on one 8.7 KB line per frame, ten
digits) converts under the default limit at 8 poles and 1.5e-5, and matches
a built-in bus of 32 resistors and inductors and 23 capacitors on the through
channel and the nearest crosstalk to 2e-3 of each point's size or 1e-3 of
its largest; `-order 8` pins the resonator at 8 poles and `-maxpoles 2` on
the 4-port ladder reaches the cap and says so; `-maxpoles abc` and `-order
0` are refused naming the flag and the default; the trace prints one line
per order on the ladder. `touchstone`: a 16-port file with one 8.7 KB line
per frame reads all frames and its last element as written. On the E-749
binary the bus is refused, the flags are unknown, the trace is absent and
the long line loses a number.

## What this does not do

* The measure's floor is a thousandth of the largest element. A block whose
  meaningful elements span more than three decades — a filter's Y is not
  such a block, its stopband being small in S rather than in Y — would need
  the floor lowered; there is no flag for it.
* The file's precision still bounds a near-transparent block's fit, as
  above. Nothing interpolates or denoises the data.
* The Python `snp2va.py` keeps its own measure, cap and `--order`.
