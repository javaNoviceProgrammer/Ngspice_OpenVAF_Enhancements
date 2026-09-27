# Proposal — Touchstone blocks in the S domain: table AC, an S-domain transient model, delay extraction and passivity

*Scoped 2026-09-27, after the question "is it possible to load snp files in a better
way with `pre_snp` and use them for AC and transient, and how does Spectre handle snp
files?" Nothing here is implemented. The import path as it stands is `pre_snp`
([E-200](../../enhancements_doc/Enhancement-200.md), the converter in
[`snp2va.c`](../../ngspice-46/src/frontend/snp2va.c)), the native device
([E-242](../../enhancements_doc/Enhancement-242.md),
[`nport/`](../../ngspice-46/src/spicelib/devices/nport/)), the reader `rdsnp`
([`postcoms.c`](../../ngspice-46/src/frontend/postcoms.c)) and the Touchstone hunt of
[2026-09-26](../bug_hunts/2026-09-26_touchstone-import.md), whose eleven findings became
[E-741](../../enhancements_doc/Enhancement-741.md) to
[E-750](../../enhancements_doc/Enhancement-750.md). The measurements below were made on
the E-750 binary the same day.*

## The question

`pre_snp` turns a Touchstone file into a rational model of the block's **admittance**,
Y(s), fitted by vector fitting, and every analysis then uses that model: AC stamps
Y(jω), transient integrates the pole states, pz and noise work from the same poles and
residues. This is one design choice made three times over: the domain (Y), the source of
the AC response (the fit rather than the data) and the absence of any check on what the
fit does between and beyond the samples. Spectre's `nport` makes the opposite choices,
and the difference is not cosmetic: a lossless line, the most ordinary RF block there is,
explodes in transient here and runs there.

## What exists, and what it lacks

After E-741 to E-750 the readers take both Touchstone versions, noise rows, per-port
references, any line length, and refuse the malformed cases by name; the fit measures
its error against the block, climbs to 80 poles and reports a cap; the native device
takes any port count, gives pz and noise. A 320-case mutation fuzz of both readers
(truncations, byte flips, NUL bytes, random bytes, 1 MB lines, empty files, v2 keyword
abuse) found no crash and no hang, DC extrapolation below the file's lowest frequency
is exact for a series C, a series L and a series R fitted from 1 to 10 GHz, a 20 000
point file fits in 0.1 s, and the native and Verilog-A backends agree to the digit.

What the probes found is that the path is robust against bad files and not against
bad physics, and that the reasons are structural.

**1. The Y domain is the wrong domain for a lossless block.** The admittance of a
lossless line is infinite at DC and at every half-wave resonance. A 100 ps line
sampled from 25 MHz to 10 GHz on a 25 MHz grid has a sample at exactly 5 GHz, where
I + S is singular to rounding; the S to Y conversion turns it into about 1e16 S without
a word, and the fit that "matches" it is accepted at a reported error of 4.98e-05 (no
`-force` needed). Evaluated per frequency, that fit is 100 percent wrong in S at
10 GHz, its largest singular value is 1.043, and its static conductance matrix has a
-508 S eigenvalue. In transient the block grows a thousandfold per nanosecond and
reaches 1e22 V by 10 ns **with matched 50 Ω terminations**; the Verilog-A route gives
the same number, so the fit is the cause and not a backend. The same line fitted to
4 GHz, below its first resonance, fits to 3e-06 per point and runs cleanly; fitted to
6 GHz with no sample on the resonance it fits to 7e-04 and runs. The disaster needs one
sample on a round frequency, which is exactly where an instrument puts them.

```python
# the lossless 100 ps line that explodes: 400 points, 25 MHz .. 10 GHz (25 MHz grid)
import numpy as np, math
T = 100e-12
with open("line.s2p", "w") as f:
    f.write("# HZ S RI R 50\n")
    for fr in np.linspace(25e6, 10e9, 400):
        s21 = np.exp(-2j * math.pi * fr * T)
        f.write(f"{fr:.10e} 0 0 {s21.real:.10e} {s21.imag:.10e} {s21.real:.10e} {s21.imag:.10e} 0 0\n")
```

**2. The error figure is blind inside an element.** A series 50 Ω with a shunt 1 pF
in parallel with 1 µH, sampled over 1 Hz to 100 GHz, reports an rms relative error of
3.03e-07. The fitted conductance of Y22 is 0.01838 S instead of 0.02 at every
frequency and -0.032 S at 1 Hz, and the fit's largest singular value is 1.086 at the
154 MHz resonance: an 8 percent error and a non-passive model behind a figure that says
the fit is perfect. The element's rms over frequency is dominated by 1/(jωL) at 1 Hz,
1.6e5 S, so nothing in band is measured. E-750's floor is the cross-element cousin of
this within-element blindness; both come from measuring an rms over frequency.

**3. Non-finite data is accepted.** A reference of `R 0` or `R 1e400`, a `nan` or
`-inf` token in a row: the reader takes them (`strtod` accepts the words, the reference
is read with `atof` and never checked), the fit reports an error of exactly zero because
every comparison with nan is false, and the model file is full of nan. Seven of the 320
fuzz cases.

**4. A misaligned row silently becomes noise data.** A short or long row shifts the
v1 number stream, the frequency-fall rule then turns everything after it into the noise
block, and a 4-port fit built on 11 of 30 points is accepted with a note about 120 noise
rows. Noise rows are taken for a 4-port although v1 noise data exists for 2-ports only;
a duplicated frequency row is read as the noise block's start; and the two readers
disagree, `rdsnp` refusing a noise block that is not rows of five while `pre_snp`
truncates it.

**5. Smaller leniencies.** An unknown parameter type on the option line falls back to
S, a missing reference value to 50, trailing junk is ignored; one 1e21 outlier makes
the rest of the block negligible (error 3e-18); a NUL byte truncates a number; an
|S| of 300 passes without a word; a quoted file name is kept literally, so a path with a
space cannot be given; and an active block's noise is the positive part of Re(Y) only,
which is E-748's documented design.

Items 3 and 4 are bugs and fixable in place. Items 1 and 2 are the design.

## How Spectre does it

Spectre's `nport` reads the same files (Touchstone 1 and 2, CITIfile, its own
format) and then does four things this path does not:

* **Small-signal analyses interpolate the table.** For ac, sp, noise and xf the
  component uses the samples directly, linear or spline between them, so the response
  at a sample is the datum and a lossless resonance is just another sample. No fit is
  involved in the frequency domain.
* **Transient builds a rational model on demand, of S.** The pole-residue
  approximation is fitted automatically to accuracy targets under an order cap, and it
  is fitted to the scattering matrix, which is bounded, not to the admittance, which is
  not. Earlier releases convolved with the impulse response instead; the rational mode
  replaced it because convolution cost grows with the length of the run.
* **Delay is extracted, not fitted.** The pure delay of each element is estimated from
  its phase and applied as an ideal delay in the time domain; only the remainder is
  fitted. That is why a nanosecond of cable does not cost two hundred poles.
* **Passivity is enforced and DC is explicit.** The model is checked over the whole
  axis, inside and outside the band, and its residues are perturbed until it is passive;
  non-passive data draws a warning. The file never holds DC, so the DC value is
  extrapolated under options the user can override, and behaviour above the highest
  sample is controlled too. Noise uses Bosma's theorem for passive data and a 2-port
  file's noise parameters for an active one.

HSPICE's S-element offers the same set (delay handling, a passivity switch, a DC
value, an interpolation choice) and ADS's SnP items likewise. The mechanisms are the
industry's answer, not one vendor's.

## The design

### 1. A safety net in the converter (no new device work)

* **Refusals.** A non-finite number anywhere, a reference of zero or less or
  non-finite, a sample at which I + S is singular (|det(I + S̃)| below 1e-8, named by
  frequency, with the hint that the block is lossless or resonant there), noise rows in
  a file of other than two ports, a network block whose count is not a whole number of
  frames, and a frequency that repeats or falls inside the network block, all refused
  by name. The rows-of-five rule applied by both readers alike.
* **A per-frequency measure.** The fit's error becomes the largest, over samples and
  elements, of |S̃_fit − S̃| at that sample relative to max(|S̃_ij| at that sample,
  1e-3 × the largest element at that sample). The vector fit's least squares carries the
  same weights, so the solution is accurate where the data is small, not only where it
  is large. Case 2 above then reports its 8 percent, and case 1 its 100 percent.
* **A passivity scan.** After the fit, the largest singular value of S̃_fit on a dense
  grid from three decades below the first sample to three decades above the last, plus
  the limit at infinity, which is the D term. The largest value and its frequency go into
  the status line; above 1 + 1e-6 the fit is refused under the E-745 rule, with `-force`
  keeping the current behaviour and `-passive` (section 2) the enforcement.

### 2. An S-domain stamp with port currents

Waves with a real reference Z_i per port, G = diag(Z_i), I_i the current into port i:

    a = G^-1/2 (V + G I) / 2        b = G^-1/2 (V − G I) / 2        b = S a

which, with S̃ = G^1/2 S G^-1/2 (the per-port S̃_ij = S_ij √(Z_i / Z_j) that E-741
already forms), is

    (I − S̃) V = (I + S̃) G I

Give every port a branch-current unknown, as a voltage source has one, and stamp these
N rows against V and I with the usual ±1 entries in the KCL rows of the port nodes and
the reference. This never inverts I + S̃: at a lossless resonance I + S̃ annihilates some
vector v, but then (I − S̃) v = 2 v, so the rows keep full rank for any S from a physical
network. The cost is N extra unknowns per instance, the same as N voltage sources.

Two modes stamp those rows:

* **Table mode (AC, sp, noise, xf).** S̃(jω) interpolated from the file's samples,
  linear in real and imaginary parts by default, cubic spline on request, on the file's
  own frequency spacing. At a sample the response is the datum. Below the first sample
  and above the last the end value is held, with one Note per run naming the range the
  analysis asked for outside the file. pz is refused in table mode, since there is no
  rational form to search.
* **Rational mode (transient, pz, and AC when asked).** S̃(s) = D + Σ R_k / (s − p_k),
  fitted by the same vector fit, with states driven by the incident waves:

      x_k' = p_k x_k + a          b = D a + Σ R_k x_k

  The trapezoidal companion is the one `nportload.c` already runs per pole, only its
  input is a and its output b; x_{n+1} = α_k a_{n+1} + B_k gives b_{n+1} = (D + Σ R_k
  α_k) a_{n+1} + history, linear in V and I through a, so the branch rows stamp as in
  AC. Passivity of an S fit is the bounded test of section 1, and **enforcement** is
  singular-value clipping: at the violating frequencies decompose S̃ = U Σ W*, clip Σ to
  1 − ε, refit the residues with the poles kept and the clipped samples added as
  constraints, repeat until the scan passes or a small number of rounds is spent, and
  report the size of the perturbation in the status line.

The `.nport` file gains a form tag (`ydomain`, the current one, or `sdomain`), the port
references, and in table mode the samples themselves.

### 3. Delay extraction

For each element, the delay τ_ij is the slope of the unwrapped phase over the upper
half of the band by linear regression, clamped at zero and dropped when the phase across
the band is under a fraction of a turn. The fit is made of S̃_ij(jω) e^{jωτ_ij}; the
model stores τ_ij beside the residues. In transient the element's input is a_j(t −
τ_ij), read from a per-port history buffer of (t, a_j) with the interpolation and the
breakpoint scheduling the lossy line device already does. Elements with unequal delays
no longer share their pole states across outputs, so the state count goes from N·Np to
N²·Np for a block with delays, or to one set per distinct delay; the status line says
how many delays were extracted and their range. A 5 ns cable to 20 GHz, which no
80-pole fit can follow, then needs the few poles of its loss and dispersion.

### 4. DC and out-of-band control

The rational model's S(0) = D − Σ R_k / p_k is whatever the fit gives. The converter
adds a DC sample to the fit, by default the real part of the lowest sample (what a
delay-free block's phase extrapolates to), reports the resulting S(0) in the status
line, and takes `-dc <file>` with a one-frequency Touchstone file, or `-dc open` and
`-dc short` for the two common cases, in its place. A Note is printed when the fit's
S(0) differs from the lowest sample by more than a percent. Above the last sample the
rational model is what it is; the passivity scan of section 1 covers that region, which
is the guarantee that matters for a fast edge.

### 5. Noise in the wave form

Table and rational modes alike take the noise correlation in wave form, C = kT (I −
S̃ S̃*) for a passive block (Bosma's theorem in the domain where it needs no inversion),
as noise-wave sources on the branch rows through `NevalSrcVec` (E-748). A 2-port file
with noise rows (E-749 reads them) gets its correlation matrix from NFmin, Γopt and Rn by
the standard chain-form relations, which closes the hunt's open item on active blocks.

### 6. The flag, and the model line after it

One word should give the whole of sections 2 to 5, so the user types

    pre_snp -sdomain [-notable] [-nodelay] [-nopassive] [-dc <file>|open|short] file [module]

and gets: the fit made of S with the per-frequency weighted measure, delays extracted
first, a DC sample added, the fit scanned and clipped to passive; a `.nport` file in
`sdomain` form carrying the samples beside the poles, so the device interpolates the
table for ac, sp, noise and xf and integrates the rational model for tran and pz; and a
status line with the per-point error, the largest singular value and its frequency, the
delays extracted and S(0). The sub-flags opt out of one part each: `-notable` uses the
rational model for AC too, wanted when an AC and a transient of one model are compared
or when pz must agree with AC; `-nodelay` and `-nopassive` switch off extraction and
clipping for diagnosis; `-dc` replaces the DC sample (section 4). `-sdomain` implies
`-native`; `-osdi -sdomain` is refused by name, since the Verilog-A route cannot carry
branch currents.

**The name.** Every flag of the command says what it does (`-native`, `-osdi`,
`-maxerr`, `-maxpoles`, `-order`), and what this one selects is the domain the model is
built and stamped in; `sdomain` is also the form tag in the file, the word in the status
line and the counterpart of `ydomain`, so one word serves everywhere. A vendor's name
says who else does it, which stops being informative the day the behaviour diverges.
`-spectre` is accepted as an alias of `-sdomain` on the same handler, as `writecorner`
and `writecr` are of `writemc` (E-742), with the help text saying "the model Spectre's
nport builds"; the documentation's canonical spelling is `-sdomain`.

**The default stays `ydomain` for a while.** Everything converted so far, every suite
and the example decks are Y-domain models. Once the S-domain path has run through the
suites for a few enhancements, flipping the default and keeping `-ydomain` for the old
form is a one-line change with a Note; nothing in this proposal depends on when.

**The model line, after the flag.** The most Spectre-like spelling has no
preprocessing command at all:

    N1 p1 p2 p3 p4 0 m
    .model m nport(file="bus.s4p" passive=1 dc="open" maxpoles=40)

with the device reading the Touchstone file itself at setup and fitting on demand when
a transient or pz asks for the rational model. Once the device has the S-domain path,
that is a small addition, because the converter is by then a function the device can
call with the same options as model parameters, and the fit's status goes to the log
as a Note. `pre_snp` stays for the explicit workflow, where the model file is inspected
or reused, and for the osdi route.

## What this does not change

The Verilog-A route (`pre_snp -osdi`) cannot express branch currents as unknowns and
keeps the Y-domain model as the portable form; it gains the refusals, the measure and
the scan of section 1 and nothing else. `rdsnp` and the `.nport` reader keep reading
every file they read today. The native device's four-corner Y stamp stays for `ydomain`
models, so nothing already converted changes behaviour.

## Verification to pin (the suite)

* the lossless line above: refused by name at 5 GHz in Y form; in S form its table AC
  equals the file at every sample, its rational transient stays bounded with matched
  50 Ω loads and with a 10 nH ‖ 1 pF load over 300 ns, and its passivity scan reports
  at most 1 + 1e-6;
* the series R with shunt C ‖ L over 1 Hz to 100 GHz: reported error and per-point
  error agree to a factor of two, and the fit's largest singular value is at most 1;
* `R 0`, `R 1e400`, `nan`, `-inf`: refused by name, no model file written;
* a short row, a long row, a duplicated frequency, noise rows in a 4-port: refused by
  name, both readers alike;
* table AC of the E-750 16-port bus equals `rdsnp`'s vectors at every sample and its
  rational transient matches the built-in twin as it does today;
* a 5 ns line to 20 GHz: delays extracted, at most 12 poles, transient edge arrives at
  5 ns within a time step;
* `-dc short` on a DC-blocking file gives 0 V at the op, `-dc open` on a through gives
  the load voltage, and the Note fires when the extrapolation disagrees;
* the active 2-port with noise rows: output noise from NFmin, Γopt, Rn matches the
  closed form within 1 percent;
* `-spectre` and `-sdomain` write byte-identical model files; `-osdi -sdomain` is
  refused naming the flag; a `ydomain` file still loads and runs as today;
* the existing presnp, touchstone, nport_native, lowrank and snpfuzz suites unchanged.

## Where the code goes

* `snp2va.c`: the refusals, the weighted fit and per-frequency measure, the passivity
  scan and clipping, delay estimation, the DC sample, the `sdomain` emitter;
  `com_presnp.c`: `-sdomain` and its alias, `-notable`, `-nodelay`, `-nopassive`, `-dc`,
  and `-passive` for the Y form;
* `nport/nportmpar.c`, `nportsetup.c`: the model-line form (section 6), calling the
  converter as a function;
* `nport/nportsetup.c`: the branch unknowns (as `vsrc` allocates its current) and the
  row pointers; `nportload.c`, `nportacload.c`, `nportpzld.c`, `nportnoise.c`: the S-form
  paths beside the Y-form ones; `nportread.c`: the form tag, references, delays, samples;
* `postcoms.c`: the shared rows-of-five and frame-count rules, so `rdsnp` and `pre_snp`
  refuse alike;
* a new `snprobust` suite holding the probes above, and the fold-time additions to
  presnp, touchstone and nport_native.

## Order of work

1. One enhancement: the safety net (section 1). Turns the lossless line from a silent
   explosion into a named refusal, makes the error figure honest, and reports
   passivity. Stands alone.
2. One enhancement: the S-domain stamp with table AC and the rational transient
   (section 2) behind `-sdomain` (section 6), including enforcement. This is where the Spectre-class behaviour comes
   from and the largest piece.
3. One enhancement: delay extraction (section 3).
4. One enhancement: DC control and 2-port noise parameters (sections 4 and 5).
5. One enhancement: the model-line form (section 6), once the converter is callable
   from the device.
