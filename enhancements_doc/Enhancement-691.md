# Enhancement-691: `.probe i(n3)` on a multi-terminal OSDI device names each terminal current after the model's terminal — four vectors were all `n3:nn#branch`, and `i(n3,p)` was refused

**Scope:** F9 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_ngspice-osdi-analyses-sens-and-events.md).
ngspice: `src/frontend/inpc_probe.c` (the explicit probes on OSDI instances kept for
`inp_probe_osdi`; `probe_osdi_explicit_pass`, `probe_splice_term`, `probe_osdi_line_terms`).
`examples/probebus_examples/` (a module, five checks, 11). **ngspice only.**

**Suites:** [`probebus_examples`](../examples/probebus_examples/) 11 of 11 per solver, both
solvers (all 5 new checks fail on the E-680 binaries); `probeblock`, `probeshort`, `savecur`
unchanged; full sweep 531 of 531.

## What was wrong

```
n3 o d a 0 mvccs gm=2m
.probe i(n3)
op ; print all
    n3:nn#branch = 1.000000e-03
    n3:nn#branch = -1.00000e-03
    n3:nn#branch = 0.000000e+00
    n3:nn#branch = 0.000000e+00
```

`.probe` measures a current by putting a zero-volt source in series with a terminal and
saving its branch current under `<inst>:<terminal>#branch`. The pass runs during the deck
read, before `pre_osdi` has registered the modules, so for an `n` line the terminal-name
table had nothing to say and answered `nn` for every terminal: the four sources were
distinct (`vcurr_n3:nn:1_0` … `:4_0`) but the four vectors carried one name, which `print`,
`meas` and `wrdata` cannot tell apart. `i(n3,2)` gave one more `n3:nn#branch`; `i(n3,p)`
looked the name up in the same table and was refused ("Node p is not available for device
n3"). Enhancement-628 had moved `.probe alli`'s OSDI lines to a second pass that runs once
the modules are registered; the explicit forms had stayed behind.

## What changed

The explicit `i(<inst>)`, `i(<inst>,<k>)` and `i(<inst>,<terminal>)` probes on an OSDI
instance are kept by their text during the deck read and spliced in that second pass,
where the model's terminal names are known and the autobus shorthand of a bus line is
written out against its ports as `alli` has it:

| probe | vectors |
|---|---|
| `i(n3)` | `n3:p#branch`, `n3:n#branch`, `n3:cp#branch`, `n3:cn#branch` |
| `i(n3,2)` | `n3:n#branch` |
| `i(n3,p)`, `i(n3,cp)` | `n3:p#branch`, `n3:cp#branch` (by name, case-insensitive) |
| `i(n2)` on `N2 /mid /out vares` under `autobus=kicad` | `n2:p_k_#branch`, `n2:n_k_#branch`, k = 0..3 |
| `i(n2,6)` | the sixth terminal of the written-out line, `n2:n_1_#branch` |
| `i(n5)` on a two-terminal device | `n5#branch`, as before |

A model that cannot be resolved (no `.model` card for the line) gets the generic `nn`, as
before.

## Verification

| check | result |
|---|---|
| `i(n3)` on a four-terminal device | 1 mA, −1 mA, 0, 0 under the four terminal names; no `nn` |
| `i(n3,2)` | `n3:n#branch` = −1 mA, nothing else of n3 |
| `i(n3,p)` and `i(n3,cp)` | the two vectors (were "Node p is not available") |
| `i(n2)` on a bus line in autobus shorthand | written out, `n2:n_k_#branch` = −(k+1) mA, the outputs intact |
| `i(n2,6)` | `n2:n_1_#branch` = −2 mA, alone |
| the E-680 binaries on the suite | all 5 new checks fail |
| the probe suites; full sweep | unchanged; 531 of 531 |

## What this does not do

- `p(<inst>)` is unchanged: its vector is `<inst>:power` and its internal source names
  carry the terminal number, so they were unique already.
- `vd(n3:1:2)` on an OSDI device is refused ("Either first or second node have to be
  non-zero") by the differential probe's own parsing, which this pass does not touch.
- An instance inside a subcircuit (`i(x1.n3)`) is not found by the explicit probe, for a
  built-in device either.
