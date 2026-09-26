# Enhancement-741: `pre_snp` reads Touchstone 2 — the bracketed keywords, a per-port `[Reference]`, the `Lower`/`Upper` matrix formats and a `[Noise Data]` section — refuses by name what it cannot read instead of fitting it, counts the ports of a `.yNp`/`.zNp` file, and undoes the v1 normalization of Y and Z

**Scope:** F1, F10 and F11 of the
[Touchstone-import hunt](../docs/bug_hunts/2026-09-26_touchstone-import.md);
its F2 becomes a refusal with the cause named. One file,
`src/frontend/snp2va.c`: the `TS` record, `parse_touchstone`, `to_Y` and two
small helpers (`ts_keyword`, `ts_numbers`). The parser is shared by both
`pre_snp` backends, so `-osdi` and `-native` gain the same reading. ngspice
only. The vector fit, both emitters, the native `nport` device, `rdsnp`,
`wrsnp` and the Python `snp2va.py` are untouched.

**Suites:** [`presnp_examples`](../examples/presnp_examples/) 19 of 19 (ten
new checks; 9 of 19 on the E-739 binary); `nport_native`, `snpfuzz`,
`lowrank`, `touchstone`, `nport` and `crashfix2` unchanged; full sweep
532 of 532.

## What was wrong

The converter behind `pre_snp` parsed a Touchstone file in one pass: strip
`!` comments, read the `#` option line, and take every token `strtod` accepts
on any other line as data. Four things followed from that.

**A Touchstone 2 file was fitted to garbage, silently (F1).** A v2 file
begins with bracketed keywords, and the numbers on them — `[Version] 2.0`,
`[Number of Ports] 2`, `[Number of Frequencies] 21`, `[Reference] 50 50` —
entered the number stream ahead of the first frequency, so every frame was
misaligned. The frame count was `nn / rec` with the remainder dropped, so
nothing noticed. On the hunt's RC two-port, S12 set to a tenth of S21:

| file | `pre_snp` report | `S_2_1` at 100 kHz |
|---|---|---:|
| v1, same data | 2-port, 2 poles, rms rel err 4.04e-04 | 0.49968 − j0.01172 |
| v2 | 2-port, 16 poles, rms rel err 5.92e-02 | **−66.7 − j1.4e-5** |

The rms error was printed and the model was written and used.

**A v1 file with noise-parameter rows was fitted the same way (F2).** The v1
specification lets a two-port carry `f NFmin |Γopt| ∠Γopt rn/R` rows after the
network data. 214 numbers became 23 frames of 9 with 7 dropped: 6 poles, rms
error 0.42, S21 = 0.975.

**A `.y2p` or `.z2p` was read as a 1-port (F10).** Only an `.sNp` extension
counted the ports; anything else fell to a fallback that takes the first N for
which the number count divides `1 + 2N²`. A two-port frame has 9 numbers and
9 is divisible by 3, so the fallback answered 1 for every two-port file
`wrsnp out.y2p y` writes (and for every four-port, 33 = 3·11): *1-port, 18
poles, rms rel err 4.2e-2*.

**v1 Y and Z were taken as absolute (F11).** Touchstone 1 stores Y·R and Z/R;
`wrsnp` writes them so and `rdsnp` undoes it (E-72). `to_Y` copied a Y matrix
and inverted a Z matrix as they stood, so the block was fifty times too
conductive: S21 = 0.5973 − j0.4783 against 0.4997 − j0.0118. The Python
original has the same two lines, so this dates from E-199.

## What changed

`parse_touchstone` is version-aware. A bracketed line is a keyword, read
through `ts_keyword` (lower-cased, inner whitespace collapsed, so
`[Number  of Ports]` and `[number of ports]` are the same):

* `[Version]` marks the file as v2 (2.0 and 2.1 read alike here); from then
  on a numeric line before `[Network Data]` is an error rather than data.
* `[Number of Ports]` gives N (1 to 512); an `.sNp` extension that disagrees
  is refused with both numbers. A v2 file without it is refused.
* `[Two-Port Data Order] 12_21` or `21_12` sets the two-port layout; a v2
  two-port without it is refused, since the specification requires it and
  the alternative is a silent swap.
* `[Number of Frequencies]` is checked against the frames read.
* `[Reference]` takes N impedances, on the keyword line or continued over the
  following lines, and refuses a short list. `[Reference]` before
  `[Number of Ports]` is refused.
* `[Matrix Format] Full`, `Lower` or `Upper`: a triangle frame holds
  `N(N+1)/2` pairs and is mirrored.
* `[Begin Information]` … `[End Information]` is skipped whole;
  `[Number of Noise Frequencies]` is accepted; `[Noise Data]` and `[End]`
  end the network data.
* `[Mixed-Mode Order]` is refused by name with the advice to convert to
  single-ended order; an unknown keyword is refused with its name and line.
* On the option line, the v2 parameter types `G` and `H` are refused by name.

For every file, the number count must be a whole number of frames; otherwise:

```
214 numbers of network data, not a whole number of 2-port frames of 9 (frequency + 4 pairs):
a wrong port count, or Touchstone 1 noise-parameter rows after the network data, which are
not read -- remove them
```

The port count of a v1 file comes from an `.sNp`, `.yNp` or `.zNp` extension;
the divisor fallback remains for a file with none of them.

`to_Y` applies the version's normalization: a v1 file's Y is divided by R and
its Z multiplied by R before use; a v2 file's are absolute, as its
specification states. The S conversion carries per-port real references
`z_i` (all equal to the option line's `R` when there is no `[Reference]`):

```
S'_ij = S_ij · sqrt(z_i / z_j)
Y     = G⁻¹ (I − S')(I + S')⁻¹,   G = diag(z_i)
```

which is `(1/z0)(I − S)(I + S)⁻¹` when every port is `z0`, the expression used
before.

Nothing after the parse changes: the fit, the order selection, the reciprocal
mirror, the passivity projection of E, the Verilog-A and `.nport` emitters and
the status message are as they were.

## Verification

The hunt's probes on the rebuilt binary: the v2 file now reports *2-port, 2
poles, rms rel err 4.04e-04* and the same S21 and S12 as its v1 form to the
digit; the noise-parameter file is refused with the message above and no
`.nport` is written; `wrsnp`'s `.y2p` and `.z2p` report 2 ports and give
S21 = 0.4997226 − j0.0117744 against the truth 0.4997226 − j0.0117744.

The ten `[E-741]` checks in `verify_presnp.py` use `pre_snp -native` (no
compiler; the parser is the same) and compare the block against the original
network's own AC response, the tolerance the suite's earlier checks use:

| check | file | result |
|---|---|---|
| a | v2 two-port, `12_21`, `[Reference]` split over two lines, an information block | 2.2e-7 |
| b | v2 with `[Reference] 50 75`, S computed with those references | 2.7e-7 |
| c | the 3-port star as `_v2low.ts`, `[Matrix Format] Lower` | 7.4e-10, 8.4e-10 |
| d | v2 in `21_12` order with a `[Noise Data]` section | 2.2e-7 |
| e | v1 `.s2p` with three noise rows: refused, rows named, nothing written | refused |
| f | v1 `.y2p` as `wrsnp` writes it (Y·R): 2-port reported, matches | 2.2e-7 |
| g | v1 `.z2p` (Z/R) | 2.1e-7 |
| h | v2 Y file, absolute | 2.2e-7 |
| i | `[Mixed-Mode Order]`, a v2 two-port without `[Two-Port Data Order]`, `[Number of Frequencies] 999`: each refused by name | refused |

On the E-739 binary nine of the ten fail (a to i; the second half of f, the
2-port report, tested on the converter's own `(2-port,` text since the deck's
title also says 2-port). The `nport_native` suite (whose fourth check is a
`pre_snp -native` round trip), `snpfuzz` (the E-227 port-count fuzz),
`lowrank`, `touchstone`, `nport` and `crashfix2` are unchanged.

## What this does not do

* `rdsnp` is still a v1 reader: the hunt's F3 (S12/S21 swapped on a v2
  `12_21` file, `[Reference]` ignored), F4 (a noise-parameter file refused
  with *wrong port count?*) and F8 (the no-option-line default) are open.
* The noise-parameter rows are refused, not read (F2). Nothing publishes
  NFmin, Γopt or rn.
* No fit-error threshold (F5); the rms error is still only reported.
* The Python `snp2va.py` keeps its v1-only parser and its absolute reading of
  v1 Y and Z.
* Mixed-mode S-parameters, and the `G` and `H` types, are refused rather than
  converted. Complex references do not exist in Touchstone 2, so none are
  read.
* Nothing changes in the native device: the terminal-warning flood (F6), the
  `pz` abort (F7) and the missing thermal noise (F9) are as the hunt found them.
