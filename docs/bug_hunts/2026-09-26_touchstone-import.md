# Bug hunt — Touchstone import: the two readers, the converter and the n-port device

**Date:** 2026-09-26 · **Commit under test:** `0e3c7f36` · **Binaries:**
`ngspice-46/build/src/ngspice` at the E-740 state (KLU, `--disable-openmp`,
Apple clang) and `OpenVAF-master-20260610/target/opt/openvaf-r`. **Status:
open** — a survey and a set of probes, nothing in the repository was changed
by the hunt itself; F1, F10 and F11 were folded afterwards as
[E-741](../../enhancements_doc/Enhancement-741.md) and F2 became a refusal;
F3 and F8 as [E-744](../../enhancements_doc/Enhancement-744.md), which also
gave F4's refusal its cause; F5 as
[E-745](../../enhancements_doc/Enhancement-745.md); marked in the table.
Probe files and logs are under the session scratchpad `ts/`.

The question was how ngspice handles RF work that starts from a Touchstone
`.sNp` file. Stock ngspice-46 has three pieces: the `.sp` analysis measures a
circuit's S-parameters through voltage sources tagged `portnum` and `z0`,
`wrs2p` writes a two-port Touchstone v1 file, and the XSPICE `xfer` code model
interpolates one transfer function from a Touchstone-style column file in AC
only. Everything that puts a measured block *into* a circuit is this project's:
the N-port writer and the `rdsnp` reader (E-64, E-72), the `snp2va.py`
converter (E-199), the `pre_snp` command and its C converter (E-200, E-201,
E-205, E-227), the native `nport` device and `pre_snp -native` (E-242, E-243),
and the design aids `rfstab` and `pyplot -smith` (E-253, E-254). The hunt
walked that stack with one known two-port — a series 100 Ω into a shunt 1 nF
between 50 Ω ports, S12 set to a tenth of S21 so the two directions can be
told apart — written in every form the files can take, and read back through
each path.

| # | finding | severity |
|---|---|---|
| [F1](#f1--pre_snp-fits-a-touchstone-v2-file-to-garbage-silently) | *(fixed in [E-741](../../enhancements_doc/Enhancement-741.md): the converter's parser reads Touchstone 2, and refuses a number count that is not a whole number of frames)* `pre_snp` on a Touchstone v2 file keeps the numbers on the bracketed keyword lines as data, misaligns every frame and fits the result: 16 poles, rms error 5.9e-2, S21 = −66.7 where the v1 file of the same data gives 2 poles, 4e-4 and 0.4997; no message | **high** — silent wrong model |
| [F2](#f2--pre_snp-fits-a-v1-noise-parameter-block-as-s-data-silently) | *(since [E-741](../../enhancements_doc/Enhancement-741.md) the file is refused, with the count and the noise rows named; reading the rows is still open)* a v1 `.s2p` with the noise-parameter rows the v1 spec allows after the network data is fitted with those rows as S-data: 6 poles, rms error 0.42, S21 = 0.975; no message | **high** — silent wrong model |
| [F3](#f3--rdsnp-reads-a-v2-file-with-s12-and-s21-swapped-and-ignores-reference) | *(fixed in [E-744](../../enhancements_doc/Enhancement-744.md): the reader reads the v2 keywords, `Zref` carries per-port references, v2 Y/Z are absolute)* `rdsnp` drops every bracketed line whole, so a v2 file's `[Two-Port Data Order] 12_21` is not seen and S12 and S21 come back swapped; `[Reference]` per-port impedances are ignored and a v2 Y or Z file would be de-normalized as if v1 | **medium** — silent |
| [F4](#f4--rdsnp-refuses-a-valid-v1-file-that-carries-noise-parameters) | *(since [E-744](../../enhancements_doc/Enhancement-744.md) the refusal names the count, the frame and the noise rows as the usual cause; reading the rows is still open)* the same noise-parameter file is refused with *holds 214 numbers, not a multiple of 9 — wrong port count?* | low — misleading refusal |
| [F5](#f5--pre_snp-never-refuses-a-bad-fit) | *(fixed in [E-745](../../enhancements_doc/Enhancement-745.md): a fit above 0.1 rms relative error is refused with the number; `-maxerr <x>` and `-force` accept it)* the converter reports its rms error in an informational line and emits the model whatever the value; the 42 % fit of F2 was used | medium |
| [F6](#f6--every-native-nport-instance-prints-509-lines-of-unconnected-terminal-warnings) | `N1 p1 p2 0 mm` on a native `nport` model prints E-481's warning with one line per terminal from 4 to 512; the suite's own deck prints 510 | low — diagnostics flood |
| [F7](#f7--pz-aborts-on-a-circuit-with-a-native-nport-and-says-only-that-it-aborted) | `pz` with the native device prints *pz simulation(s) aborted* and nothing else; the OSDI route finds the RC pole at −1.00001e7 rad/s (plus the fit's own pole–zero pair) | medium — unsupported without a reason |
| [F8](#f8--rdsnp-defaults-a-file-with-no-option-line-to-hz-s-ri-the-spec-and-the-converter-say-ghz-s-ma) | *(fixed in [E-744](../../enhancements_doc/Enhancement-744.md): the default is GHz S MA R 50, and the warning names it)* a v1 file without an option line is read by `rdsnp` as Hz and real/imaginary; the spec's default, which the converter applies, is GHz and magnitude/angle | low |
| [F9](#f9--an-imported-lossy-block-is-noiseless) | neither backend has a noise entry: the native device's table has no `DEVnoise`, the emitted Verilog-A has no noise source; `.noise` through the RC two-port reports 3.4e-13 V/√Hz against the built-in's 1.09e-9, and the noise figure of `.sp` through a lossy filter or package is that of the rest of the circuit, silently | medium — wrong numbers, by design gap |
| [F10](#f10--a-y2p-or-z2p-file-is-read-as-a-1-port) | *(fixed in [E-741](../../enhancements_doc/Enhancement-741.md): the port count is taken from a `.yNp`/`.zNp` extension too)* `pre_snp` on the `.y2p` and `.z2p` files `wrsnp` writes reports *1-port, 18 poles, rms rel err 4.2e-2*: the port count is inferred only from an `.sNp` extension and the fallback picks the first divisor, which is 1 for every two-port frame of 9 numbers | **medium** — silent wrong model |
| [F11](#f11--pre_snp-takes-v1-y-and-z-data-as-absolute-the-spec-wrsnp-and-rdsnp-normalize-them-to-r) | *(fixed in [E-741](../../enhancements_doc/Enhancement-741.md): v1 Y and Z are de-normalized, v2's taken as absolute)* with the port count right, the same Y file gives S21 = 0.597 − j0.478 against 0.4997 − j0.0118: v1 Y and Z data are normalized to the reference resistance (`wrsnp` writes Y·R and Z/R, `rdsnp` undoes it) and the converter takes them as absolute; the Python original does the same | **medium** — silent wrong model |

---

## F1 — `pre_snp` fits a Touchstone v2 file to garbage, silently

The v2 form of the two-port, 21 points from 100 kHz to 1 GHz:

```
[Version] 2.0
# Hz S MA
[Number of Ports] 2
[Two-Port Data Order] 12_21
[Number of Frequencies] 21
[Reference] 50 50
[Network Data]
100000 0.499923 -0.450 0.049986 -1.350 0.499861 -1.350 0.500416 -4.048
...
[End]
```

`pre_snp -native` on it, then the block between two `.sp` ports:

| file | `pre_snp` report | `S_2_1` at 100 kHz |
|---|---|---:|
| v1, same data | 2-port, 2 poles, rms rel err 4.04e-04 | 0.49968 − j0.01172 |
| v2 | 2-port, 16 poles, rms rel err 5.92e-02 | **−66.7 − j1.4e-5** |
| truth (`rdsnp` of the v1 file) | | 0.49972 − j0.01178 |

The parser ([`snp2va.c:163-190`](../../ngspice-46/src/frontend/snp2va.c))
strips `!` comments, reads the `#` option line, and treats every other line
as data by keeping each token `strtod` accepts. `[Version] 2.0` contributes
`2.0`, `[Number of Ports] 2` contributes `2`, `[Number of Frequencies] 21`
contributes `21`, `[Reference] 50 50` contributes two more, so the number
stream starts five values early and every frame is misaligned. The frame
count is then `nn / rec` with the remainder dropped
([`snp2va.c:205-207`](../../ngspice-46/src/frontend/snp2va.c)), so nothing
notices. The `-osdi` route shares the parser and produces the same model.

*Fixed in [E-741](../../enhancements_doc/Enhancement-741.md).* The parser reads the v2 keywords, takes the port count from `[Number of Ports]`, the two-port order from `[Two-Port Data Order]`, per-port impedances from `[Reference]`, and refuses a number count that is not a whole number of frames. The v2 file above now fits to 2 poles and 4.04e-4, the same model as its v1 form.

## F2 — `pre_snp` fits a v1 noise-parameter block as S-data, silently

The v1 specification lets a two-port file carry noise parameters after the
network data — one row per frequency of `f NFmin |Γopt| ∠Γopt rn/R` — and
marks the boundary by the frequency dropping back below the previous line's.
A file with the 21 network rows followed by five noise rows:

| file | `pre_snp` report | `S_2_1` at 100 kHz |
|---|---|---:|
| v1 with a noise block | 2-port, 6 poles, rms rel err 4.25e-01 | **0.975 − j0.022** |

Same mechanism as F1: 214 numbers, 23 frames of 9 taken, 7 numbers dropped,
and the frames after the boundary are noise rows read as S-data.

*Since [E-741](../../enhancements_doc/Enhancement-741.md)* the same file is refused: *214 numbers of network data, not a whole number of 2-port frames of 9 (frequency + 4 pairs): a wrong port count, or Touchstone 1 noise-parameter rows after the network data, which are not read -- remove them*. Reading the rows, and publishing the noise parameters, is still open.

## F3 — `rdsnp` reads a v2 file with S12 and S21 swapped, and ignores `[Reference]`

`rdsnp` on the v2 file of F1:

| file | `S_2_1[0]` | `S_1_2[0]` |
|---|---:|---:|
| v1 | 0.49972 − j0.01178 | 0.049972 − j0.001178 |
| v2, `12_21` | **0.049972 − j0.001178** | **0.49972 − j0.01178** |

The reader ([`postcoms.c:722-752`](../../ngspice-46/src/frontend/postcoms.c))
scans a data line with `sscanf(" %lg")`, which fails at the `[`, so a
bracketed line yields no numbers and is dropped whole. That keeps the frame
count right, which is why `rdsnp` does not share F1, but it also drops
`[Two-Port Data Order]`, so a `12_21` file is read in the v1 `21_12` order,
and `[Reference]`, so per-port impedances are lost and `Rbase` falls back to
the option line's `R` or 50. A v2 Y or Z file, which the v2 spec stores
un-normalized, would be divided or multiplied by `Rbase` as if it were v1.

*Fixed in [E-744](../../enhancements_doc/Enhancement-744.md).* The reader reads the v2 keywords; the file above now gives S21 = 0.49972 − j0.01178 and S12 = 0.049972 − j0.001178, the v1 numbers, announced as Touchstone 2. A per-port `[Reference]` is published as `Zref` with `Rbase` port 1's, a `Lower`/`Upper` matrix is mirrored, a v2 Y or Z file is taken as written, and mixed-mode order, the G/H types and a two-port without its data order are refused by name.

## F4 — `rdsnp` refuses a valid v1 file that carries noise parameters

```
Error: v1noise.s2p holds 214 numbers, not a multiple of 9 (1 + 2*2^2) -- wrong port count?
```

The count check is right to fire; the message names a cause that is not the
one, and the file is one every VNA can write.

*Since [E-744](../../enhancements_doc/Enhancement-744.md)* the refusal reads: *holds 214 numbers of network data, not a whole number of 2-port frames of 9 (frequency + 4 pairs): a wrong port count, or Touchstone 1 noise-parameter rows after the network data, which rdsnp does not read -- remove them, or give the port count*. Reading the rows is still open, as it is for the converter (F2).

## F5 — `pre_snp` never refuses a bad fit

The order-selection loop ([`snp2va.c:661-726`](../../ngspice-46/src/frontend/snp2va.c))
climbs the pole count, keeps the best stable fit and returns *chosen, else
best, else previous*. The rms error goes into the status message
(`2-port, 6 poles, rms rel err 4.25e-01`) and nowhere else: no threshold, no
warning, and the model of F2 was written and used. A user who does not read
the informational line has no signal.

*Fixed in [E-745](../../enhancements_doc/Enhancement-745.md).* A fit whose worst element's rms relative error is above 0.1 is refused before anything is written, with the error, the pole count, the limit, the usual causes and the flags: `pre_snp -maxerr <x>` raises the limit for that command, `-force` removes it, and a fit accepted that way says so. The status line now reports the returned fit's own error.

## F6 — every native `nport` instance prints 509 lines of unconnected-terminal warnings

```
Warning: instance n1: 509 of the 512 terminals of model type 'nport' are not connected.
         terminal 4 ('4') is absent
         terminal 5 ('5') is absent
         ...
         terminal 512 ('512') is absent
         The model sees $port_connected() = 0 for these, and any branch
         to them carries no current. They are NOT grounded -- connect
         them to 0 explicitly if that is what you meant.
```

E-481's warning ([`inp2n.c:1214-1233`](../../ngspice-46/src/spicelib/parser/inp2n.c))
compares the line's node count with the device's `terms`, and the native
device declares `NPORT_MAXTERMS` = 512 as its terminal count
([`nportdefs.h`](../../ngspice-46/src/spicelib/devices/nport/nportdefs.h))
because its port count is only known from the model. The suite's own
`_rc_ac.cir` prints 510 lines. The text about `$port_connected()` is written
for compiled modules and means nothing here.

## F7 — `pz` aborts on a circuit with a native `nport`, and says only that it aborted

The RC two-port driven at p1, output at p2, `pz p1 0 p2 0 vol pz`:

| block | result |
|---|---|
| built-in R and C | `pole(1) = −1.00000e+07` |
| `pre_snp -native` | `pz simulation(s) aborted` — no other line |
| `pre_snp -osdi` | `pole(3) = −1.00001e+07`, plus the fit's pole pair at −2.61e7 ± j4.87e9 nearly cancelled by a zero pair at −2.61e7 ± j4.87e9, and two *iteration limit reached* warnings |

The native device's table ([`nportinit.c:44-66`](../../ngspice-46/src/spicelib/devices/nport/nportinit.c))
sets `DEVpzSetup` but leaves `DEVpzLoad` NULL, so the pole-zero matrix never
contains the block, the output node hangs on its 1 GΩ load and the analysis
gives up without naming the device. Its admittance helper already evaluates
Y at a complex `s`, so a pz load is a stamp away. The OSDI route works, with
the caveat that a rational fit brings its own poles and zeros.

## F8 — `rdsnp` defaults a file with no option line to Hz, S, RI; the spec and the converter say GHz, S, MA

[`postcoms.c:753`](../../ngspice-46/src/frontend/postcoms.c) warns *assuming
Hz S RI R 50*; the Touchstone specification's default for a missing option
line is `# GHz S MA R 50`, which the converter's parser applies
([`snp2va.c:158`](../../ngspice-46/src/frontend/snp2va.c)). The two readers
disagree on the same file. Measured on the two-port written in GHz and MA
without its option line: `rdsnp` reports `frequency[0] = 1.0e-04` for the
100 kHz point and `S_2_1[0] = 0.49986, -1.35`, the magnitude and the angle in
degrees taken as real and imaginary parts.

*Fixed in [E-744](../../enhancements_doc/Enhancement-744.md).* The default is the specification's, GHz S MA R 50, and the warning names it; the option-less file above now reads 100 kHz and 0.49972 − j0.01178.

## F9 — an imported lossy block is noiseless

The native device's table has `DEVnoise = NULL`; the emitted Verilog-A of the
`-osdi` route has no `white_noise` or `flicker_noise` contribution (nothing in
`snp2va.c` emits one). A block imported from a measured filter, package or
cable therefore contributes no thermal noise to `.noise`, and the noise figure
`.sp` computes through it is that of the surrounding circuit only. Measured,
`noise v(p2) Vin lin 1 1meg 1meg` on the RC two-port:

| block | `onoise_spectrum` at 1 MHz |
|---|---:|
| built-in R and C | 1.090e-9 V/√Hz |
| `pre_snp -native` | 3.447e-13 V/√Hz — the 1 GΩ load's noise through the block, nothing from the 100 Ω |

The physics is fixed by the data: a passive network at temperature T has the
noise current spectrum 4kT·Re(Y), so both backends could add it from the
fitted Y without new inputs.

## F10 — a `.y2p` or `.z2p` file is read as a 1-port

`wrsnp out.y2p y` and `wrsnp out.z2p z` write the two-port in Y and Z form
(E-72). `pre_snp -native` on each:

| file | `pre_snp` report | `S_2_1` at 100 kHz |
|---|---|---:|
| `.s2p` | 2-port, 2 poles, rms rel err 4.96e-07 | 0.49972 − j0.01177 |
| `.y2p` | **1-port**, 18 poles, rms rel err 4.21e-02 | 0.977 |
| `.z2p` | **1-port**, 10 poles, rms rel err 1.98e-01 | 0.973 |

The port count is inferred from the extension only when it is `.sNp`
([`snp2va.c:196`](../../ngspice-46/src/frontend/snp2va.c)); otherwise the
fallback takes the first N for which the number count divides `1 + 2N²`.
A two-port frame has 9 numbers and 9 is divisible by 3, so the fallback
answers 1 for every two-port file, and likewise for a four-port (33 = 3·11).
The option line's `Y` or `Z` is read correctly; only the count is wrong.

*Fixed in [E-741](../../enhancements_doc/Enhancement-741.md).* A `.yNp` or `.zNp` extension counts the ports as `.sNp` does; the two files above are read as 2-ports and, with F11, fit to 5e-8 and 1e-7.

## F11 — `pre_snp` takes v1 Y and Z data as absolute; the spec, `wrsnp` and `rdsnp` normalize them to R

Renaming the two files to `.s2p` so the port count is right (the option
line still says `Y` or `Z`):

| file | `pre_snp` report | `S_2_1` at 100 kHz |
|---|---|---:|
| Y data, 2-port | 2 poles, rms rel err 5.19e-08 | **0.5973 − j0.4783** |
| Z data, 2-port | 2 poles, rms rel err 1.17e-07 | **0.5973 − j0.4783** |
| truth | | 0.49972 − j0.01177 |

Touchstone v1 stores Y·R and Z/R (v2 stores them un-normalized, which is one
of the version's changes). `wrsnp` writes them so and `rdsnp` divides and
multiplies by `Rbase` on the way back (E-72). The converter's `to_Y`
([`snp2va.c:246-247`](../../ngspice-46/src/frontend/snp2va.c)) copies a Y
matrix as it stands and inverts a Z matrix as it stands, so the block is
fifty times too conductive. The Python original,
[`snp2va.py:282-283`](../../examples/nport_examples/snp2va.py), has the same
lines, so this dates from E-199. The first row of the Y file reads
`Y11 = 0.5`, which is 1/100 Ω × 50.

---

*Fixed in [E-741](../../enhancements_doc/Enhancement-741.md).* A v1 file's Y is divided by R and its Z multiplied by R before the conversion; a v2 file's are taken as absolute, as its specification says. The Y and Z files above now give S21 = 0.49972 − j0.01177, the truth. The Python `snp2va.py` is unchanged.

## What was checked and holds

* `wrsnp` then `rdsnp` of the two-port in S, Y and Z form round-trips to the
  file's own precision; `rdsnp` of a v1 file with a non-reciprocal S keeps
  S12 and S21 apart (0.04997 against 0.4997).
* `pre_snp` on a clean v1 RI file written by `wrsnp` fits to 5e-7 rms with
  2 poles; on the same data at six digits in MA form, 4e-4. Both backends —
  `-native` and `-osdi` with the compiler — give S21 and S12 equal to the
  digit, and reciprocity is detected from the data (`is_reciprocal`), not
  assumed, so the non-reciprocal file keeps S12 = 0.1·S21 through the fit.
* The `.sp` analysis runs with an imported block between its ports, on both
  backends; `pz` through the OSDI block finds the physical pole.
* E-481's warning text is right for compiled modules; only its count is
  wrong for the native device (F6).
* The XSPICE `xfer` code model was read, not run: it is AC-only by design
  and says so in transient.

## Coverage, honestly

* One two-port, generated from a formula, not a VNA file; the v2 files were
  written by hand from the specification, and `[Matrix Format] Lower/Upper`,
  `[Mixed-Mode Order]`, the `.ts` extension and the v2 G/H parameter types
  were not tried.
* F9's OSDI half is stated from the emitter (no noise source in the emitted
  Verilog-A), only the native half was run; F7's native abort was run, its
  cause is read from the table.
* Nothing was run under `hb` or `pss` with an imported block; no suite does
  either.
* `rfstab` and `pyplot -smith` were not exercised.
* One machine, one run per number.
