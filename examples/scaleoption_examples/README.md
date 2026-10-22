# scaleoption_examples — `.option scale` is applied to compiled instances (Enhancement-915)

```
python3 verify_scaleoption.py
```

10 checks, both solvers (7 fail on E-913).

## The need

F2 of the 2026-09-26 options-and-convergence hunt. `.option scale` multiplies a built-in MOSFET's
w, l, ps and pd by the scale, and its as and ad by the square. Nothing scaled a compiled instance:
a compiled BSIM4 with `w=1 l=0.1` under `scale=1e-6` was a transistor one metre wide.

## What changed

The compiled layer scales the instance parameters of those names when it can tell they are
geometry:
- declared in metres (square metres for as, ad);
- or declared with no units and a description that says length, width, perimeter (area).

The other cases:
- a parameter of those names with no units and no description is used as written, with a
  warning;
- a model with its own `scale` parameter (the CMC convention) applies the scale itself and is not
  scaled again;
- a value reads back as written, so a `.dc` sweep of it restores what it found.

## The checks

- **[1]** Each of w, l, ps, pd and as, ad under scale=1e-6 against its value in metres.
- **[2]** `@n1[w]` reads back as written; a `.dc` sweep of it leaves the point as it was.
- **[3]** `alter` under scale.
- **[4]** An `l` in henries is not scaled.
- **[5]** A `w` with no units and no description: used as written, one warning.
- **[6]** A model with its own `scale` parameter is not scaled twice.
- **[7]** The VA-Models BSIM4 with junction geometry, and the built-in BSIM4.
- **[8]** PSP103.
