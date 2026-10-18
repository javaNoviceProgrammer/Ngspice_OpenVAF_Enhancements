# Enhancement-905: TXL's and CPL's characteristic-admittance history takes each term's own slope — a TXL above its RC corner was 3.9e-4 off the exact line, 1.3e-6 now

**Scope:** found while digging into F9 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md)
([E-904](Enhancement-904.md)).

ngspice:
- `spicelib/devices/txl/txlload.c` (`update_cnv_txl`), `spicelib/devices/cpl/cplload.c`
  (`update_cnv`): the history of the characteristic-admittance convolution advances each term with
  its own slope, in the exact weights of the step the load took.
- `include/ngspice/swec.h`: `hstep` on both lines.

**ngspice only.**

**Suites:**
- [`txlcpl_examples`](../examples/txlcpl_examples/): check [3].
- The full sweep: 596 of 596.

## What was wrong

The characteristic admittance is a constant plus three terms c·e^(x·t). Once a time point is
accepted, the convolution's history advances by the step's integral, the input linear over the
step. That integral has a slope part, dv·(c/x) for each term, and the code formed it as

```
bi *= t;    /* t = c/x of this term */
```

inside the loop over the terms. The first term took dv·t₀; the second dv·t₀·t₁; the third
dv·t₀·t₁·t₂. Whenever a node moved, two of the three terms were advanced with a wrong slope. Both
TXL and CPL had it.

The corrected slope part is a difference of two nearly equal quantities, (e − 1)·dv·t/x − dv·t·h·e,
when the step h is short against the pole. It loses digits at high frequency, where the
transient's step is a small fraction of 1/x.

## The change

- Each term takes its own slope.
- The step's integral is written in the weights of a linear segment, t·(v_new·w_n + v_old·w_o),
  w_n = (e^z − 1 − z)/z and w_o = (e^z − 1) − w_n with z = x·h, by a series where z is small. For
  TXL these are the weights of the step the load just took ([E-906](Enhancement-906.md)), kept as
  `hstep`.

## The checks

`txlcpl_examples`:
- **[3]** A TXL driven above its RC corner (the campaign's Family G seed 104, at 2.5 R/L): the
  transient's fundamental within 1e-5 of the exact line, 1.3e-6. E-903: 3.9e-4.

The campaign's Family G, 40 TXL and 40 CPL lines, the transient's fundamental against the exact line
(with E-904, E-906 and E-907):

| | median | 90th percentile | max | per line |
|---|---|---|---|---|
| TXL, E-903 | 1.7e-4 | 3.5e-3 | 6.0e-2 | |
| TXL, now | 4.5e-5 | 3.2e-3 | 6.0e-2 | 22 better (to 649x), 12 the same, 6 worse (to 3.4x, all below 1e-4) |
| CPL, E-903 | 2.4e-3 | 6.2e-2 | 0.48 | |
| CPL, now | 2.4e-3 | 6.2e-2 | 0.48 | 4 better, 35 the same, 1 worse (1.4x) |

"The same" is within 25 %. The largest errors are the lines' fits, not their history: see
[E-908](Enhancement-908.md).
