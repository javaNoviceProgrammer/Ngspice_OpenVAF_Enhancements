# seedrepeat_examples — Enhancement-891

[E-891](../../enhancements_doc/Enhancement-891.md): F3 of the
[nonlinear correctness campaign of 2026-10-15](../../docs/bug_hunts/2026-10-15_ngspice-openvaf-r-nonlinear-correctness-campaign.md).

The first `setseed 11` and every later one gave different streams to the control-language draws,
because `checkseed()` remembered the seed it had applied and `setseed` never told it. Now every
`setseed N` draws the first one's stream.

The checks:
- **[1]** After a second `setseed 11`, `sgauss`, `sunif`, `rnd`, `poisson` and `exponential` draw
  what they drew after the first.
- **[2]** The first `setseed 11` still draws −0.81594714, 0.65480624, −0.47049274.
- **[3]** A Monte Carlo loop of `sgauss` draws repeated after `setseed 1` gives the same result.
- **[4]** (control) `setseed 11`, `12`, `11` gives the 11 stream again.
- **[5]** (control) `.param` `agauss` after `setseed 5` and `reset` draws the same value both times.

Run: `python3 verify_seedrepeat.py` (5 checks per solver). On the E-888 binaries [1] and [3] fail.
