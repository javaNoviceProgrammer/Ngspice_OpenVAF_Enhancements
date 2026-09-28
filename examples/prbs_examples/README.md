# prbs_examples — Enhancement-752

A built-in pseudo-random bit sequence source for the independent voltage and
current sources:

```
Vtx tx 0 PRBS(v1 v2 tbit [td [tr [tf [order [seed]]]]])
Itx 0 rx PRBS(0 1m 100p)
Vp4 tx 0 PAM4(v1 v2 tsym [td [tr [tf [order [seed]]]]])
```

`v1` is the level of a 0 bit, `v2` of a 1 bit, `tbit` the bit period, `td` the
delay before the first bit (`v1` is held until then), `tr` and `tf` the rise
and fall times (0 or omitted: the analysis's own step, as PULSE does), `order`
the length of the shift register (2..31, default 7) and `seed` its nonzero
initial contents (default all ones). The bits come from a Fibonacci LFSR with
the standard maximal-length taps, ITU-T O.150's for 7, 9, 11, 15, 23 and 31
and IEEE 802.3's x^13 + x^12 + x^2 + x + 1 for 13, so PRBS7 repeats every 127
bits with 64 ones and PRBS31 every 2^31 − 1 bits. `PAM4` reads the same
register two bits per symbol, Gray coded (00, 01, 11, 10 are the four evenly
spaced levels from v1 to v2), which is PRBS13Q at order 13 and PRBS31Q at 31.

```
python3 verify_prbs.py
```

42 checks per solver, both solvers:

- **[1]** 254 bits of PRBS7 are the reference LFSR's, bit for bit, on the
  voltage and on the current source; period 127, 64 ones, longest runs 7 ones
  and 6 zeros; the levels are exactly v1 and v2.
- **[2]** every transition's start and end is a time point (the source
  schedules its corners as PULSE does); the edges are linear over tr and tf; a
  bit that repeats its predecessor is flat to 1e-12 for its whole period.
- **[3]** order 9 gives the x^9 + x^5 + 1 stream with period 511; a seed of 1
  gives the reference with that register, a rotation of the all-ones cycle;
  order 15 with levels −0.5/0.5; PRBS31 at 10 Gb/s for ten thousand bits,
  under a second.
- **[4]** omitted tr/tf take one step; `td=3n` holds v1 to 3 ns and shifts the
  stream.
- **[5]** `dc 0.3 PRBS(0 1 ...)`: the operating point reads 0.3, the transient
  starts at v1.
- **[6]** nine refusals by name: fewer than three values, a zero or negative
  bit time, a negative delay, a rise or fall time longer than the bit, an order
  outside 2..31, a zero seed, a seed whose low bits are zero; the current
  source refuses with its own name.
- **[7]** `alter @vtx[prbs] = [ 0 1 2n ... ]` re-reads the list; two runs in
  one session give the same stream (the register is re-armed per run, under
  E-498's rule).
- **[8]** the taps table: every register length 2..20 runs its full 2^n − 1
  period in a Python re-implementation of the same feedback.
- **[9]** PRBS7 at 2 Gb/s through a 250 ps RC channel gives E-207's `eye` an
  open eye.
- **[10]** PAM4: 16382 symbols of order 13 are the PRBS13Q reference's, the
  symbol period is 8191 with 2047, 2048, 2048, 2048 symbols per level, the
  levels at the symbol centres are exactly v1, v1 + span/3, v1 + 2 span/3, v2
  (also with −0.6/0.6), a rising and a falling edge between levels are linear
  over tr and tf, the current source gives the same stream, order 31 is
  PRBS31Q, three refusals name `pam4` and the symbol time, and an
  `alter @vtx[pam4] = [...]` turns a PRBS source into a PAM4 one.

On the E-751 binary, which has neither keyword, 1 of 27 passes (the Python
taps check; the data checks are skipped when a run fails).
