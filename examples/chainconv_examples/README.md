# chainconv_examples — a non-finite step no longer slips past the compiled MOSFET limiter (Enhancement-917)

```
python3 verify_chainconv.py
```

9 checks, both solvers (6 fail on E-913).

## The need

F3 of the 2026-09-26 options-and-convergence hunt. A chain of 600 or more compiled BSIM4
common-source stages took 73 to 363 iterations for its operating point, through dynamic gmin
stepping, every far stage loading NaN.

The first Newton step through hundreds of inverting stages overflows, and the far nodes come back
as ±∞. The E-543 limiter brought each device's step back to a finite one. It then judged "did it
move" with a tolerance proportional to the raw value: ∞ > ∞ is false, so it kept the raw point,
and the device was evaluated at infinite node voltages.

## What changed

A raw voltage that is not finite has moved. The chain converges in 9 iterations at every length,
under both solvers, on the same point; the built-in chain still needs gmin stepping.

F4 of the same hunt, the long-chain transient rejecting 2–3× the built-in's timepoints, does not
reproduce at E-913. Check [4] keeps it so.

## The checks

- **[1]** 600, 1000 and 3000 stages: at most 12 iterations, no gmin stepping, nothing non-finite.
- **[2]** … the built-in BSIM4 chain's point, to 1e-5 V.
- **[3]** (Reference.) The built-in chain of 1000 stages goes through gmin stepping.
- **[4]** The 1000-stage transient rejects no more than 1.5× the built-in's points.
