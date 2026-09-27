# Enhancement-749: both Touchstone readers read the noise-parameter block — `rdsnp` publishes NFmin, SOpt and Rn in a plot of their own, `pre_snp` counts the rows and says the model does not use them, and neither refuses a file for carrying them

**Scope:** F2 and the second half of F4 of the
[Touchstone-import hunt](../docs/bug_hunts/2026-09-26_touchstone-import.md).
`src/frontend/snp2va.c` (`parse_touchstone`: the v1 frequency-drop rule, the
v2 `[Noise Data]` section, the rows in the `TS` record, the status note),
`src/frontend/postcoms.c` (`com_read_sparam`: the same split, the noise
plot), `examples/presnp_examples/` (one refusal check replaced by two
reading checks, and a count on the v2 section), `examples/touchstone_examples/` (one replaced by three).
**ngspice only.** The fit, both emitters and the native device do not use
the rows.

**Suites:** [`presnp_examples`](../examples/presnp_examples/) 26 of 26 (23
of 26 on the E-748 binary), [`touchstone_examples`](../examples/touchstone_examples/)
26 of 26 per solver, both solvers (23 of 26 on the E-748 binary);
`snpfuzz`, `nport_native`, `lowrank`, `rfanalyses` unchanged; full sweep
532 of 532.

## What was wrong

A Touchstone 1 two-port file may carry noise parameters after its network
data — one row per frequency of `f NFmin |Γopt| ∠Γopt Rn/R` — and a
Touchstone 2 file carries them in a `[Noise Data]` section. Every VNA that
measures noise writes them. E-741 and E-744 made both readers refuse such a
file with the rows named as the likely cause (before that the converter
fitted the rows as S-data and the reader called them a wrong port count),
which was honest but left the file unusable without editing it: the network
data behind the rows was refused with them.

## What changed

**Where the block begins.** In a v1 file the noise rows follow the last
frame, and the specification tells them apart by their frequency: the first
noise frequency is at or below the last network frequency. Both parsers now
walk the frames while the frequency rises and hand what follows the first
fall to the noise block; what remains must be a whole number of rows of
five, or the file is refused naming the block and its five columns. In a v2
file `[Noise Data]` opens the block and `[End]` closes it, where E-741 and
E-744 had stopped reading at the keyword. The v1 port-count fallback for a
file with no `.sNp` extension allows for the block too.

**What each reader does with the rows.** `rdsnp` builds a second plot,
*Touchstone noise import <file>*, since the rows have frequencies of their
own: `frequency` in Hz, `NFmin` in dB, `SOpt` complex from its magnitude
and angle, `Rn` in ohms — a v1 file stores it normalized to R and is
de-normalized, a v2 file stores it absolute — under the names the `.sp`
noise analysis publishes, so imported and simulated noise parameters
compare in one expression. The network plot stays current and the summary
says both:

```
2-port S-parameters (21 points) read from v1noise.s2p into plot 'sp1'
5 noise-parameter points (NFmin, SOpt, Rn) read from v1noise.s2p into plot 'sp2'; plot 'sp1' stays current
```

`pre_snp` keeps the rows in its parse record, fits the network as before
and says so on its status line:

```
pre_snp: v1noise.s2p -> v1noise.nport  (2-port, 2 poles, rms rel err 4.04e-04; 5 noise-parameter rows read, not used by the model)
```

The count refusal that named the rows now names a malformed file, since the
rows are no longer a cause.

## Verification

`presnp`: the v1 resonator with three noise rows converts through
`pre_snp -native`, the block matches the resonator's AC response to 2e-7,
and the status line reports the three rows; the v2 file with a `[Noise
Data]` section reports its two. `touchstone`, both solvers: a v1 file with
two noise rows gives the network plot as before, current after the read,
and a noise plot with NFmin 2.0 and 2.5 dB, SOpt 0.3 at 20°, Rn 25 and 30 Ω
(0.5 and 0.6 times 50) at 1 MHz in Hz; a v2 `[Noise Data]` row lands with
Rn 0.5 Ω absolute; a row of four is refused naming the block and its five
columns. On the E-748 binary the reading checks fail as refusals and the
malformed block is refused with the frame message instead.

## What this does not do

* The rows are read, not used. Neither backend builds a noise model from
  NFmin, Γopt and Rn: the native device's noise (E-748) is the thermal
  noise of a passive block from 4kT·Re(Y), and an amplifier's Touchstone
  file still gives a model with the wrong noise. Turning the four
  parameters into the two-port's noise correlation matrix is the next
  step, separate from reading them.
* `wrsnp` writes no noise block.
* A v1 file whose noise frequencies do not fall back — a block that starts
  above the last network frequency, against the specification — is read
  as network data and refused by the frame count.
