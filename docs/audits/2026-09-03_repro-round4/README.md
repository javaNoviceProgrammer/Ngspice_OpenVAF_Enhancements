# Reproduction decks — LRM audit round 4 (2026-09-03)

Every finding in [`../2026-09-03_LRM-audit-round4.html`](../2026-09-03_LRM-audit-round4.html)
was reproduced with the files here, against the **committed** binaries in
`bin/macos/apple-silicon/` (tree at `04e42be2`) and against the locally built
`OpenVAF-master-20260610/target/opt/openvaf-r` + `ngspice-46/build/src/ngspice`.
The two runs of the whole set are byte-identical.

## Running the set

```
./run_all.sh
./run_all.sh ../../../OpenVAF-master-20260610/target/opt/openvaf-r ../../../ngspice-46/build/src/ngspice
```

`run_all.sh` compiles every `.va` here and runs the `.cir` of the same name when
there is one, printing the first compile error (or `ok`) and the lines that carry
the measurement (`OSDI` display output, printed vectors, noise spectra, singular-matrix
warnings). To run one deck by hand:

```
openvaf-r <name>.va -o <name>.osdi
ngspice -b <name>.cir
```

`incline.va` includes `inc/sub2.vah`; keep the directory layout.

## Which deck shows which finding

| deck | finding |
|---|---|
| `discovr.va` / `discovr.cir` | **§3** — a discipline's `flow.abstol = 10u` override is dropped: `a.flow.abstol` and the nature derived from `ttl.flow` both read `1e-6` |
| `swnoise2.va` / `swnoise2.cir` | **§3** — a noise-only `V(p,n) <+ white_noise(...)` in the arm after a flow contribution is dropped (only the load's `4.07e-9` remains); `swnoise.va` with `sw=1` is the control that works |
| `swnoise.va` / `swnoise.cir` | **§3** — flow-arm noise on a switch branch with netlist `m=9` reads `2.7e-3` instead of `3e-4`; the same module wrapped with `#(.$mfactor(9))` is right |
| `icint.va` / `icint.cir` | **§3** — `.ic v(n1#mid)=0.2` under `uic` is ignored on the OSDI internal node while `.ic v(2)=0.3` is honoured |
| `strrep.va` | **§3, §4** — line 6: `"hello\0world"` prints `hello`; line 17: `{i{"Hi"}}` is refused (LRM 3.3 marks it OK) |
| `hexlit.va` | **§4** — `32 'h 12ab_f001` (LRM 2.6.1 Example 5), `'h 1f`, `'h 1e5` are lexed as real numbers. **Fixed** the same day (a lexer digit-run mode after a bare base token, plus the parser accepting macro-substituted number tokens as digits); the deck compiles clean on the fixed compiler and reproduces only against the binaries the audit measured (`04e42be2`). Pinned by four new checks in `examples/lrmlex_examples/` |
| `nullarg.va` | **§4** — null arguments to `cross`/`above`/`timer` (LRM 5.10.3.1's sample-and-hold) are a type error |
| `macroq.va` | **§4** — the `` `" ``, `` `\`" `` and ``` `` ``` macro operators are lexer errors |
| `incline.va` + `inc/sub2.vah`, `incline.cir` | **§4** — `` `__LINE__ `` inside an included file is refused |
| `linedir.va` / `linedir.cir` | **§4** — `` `line 500 "fake.va" 0 `` has no effect on `` `__LINE__ ``/`` `__FILE__ `` |
| `realtoint.va` | **§4** — a real argument to an `integer` function input is a type error |
| `timerchg.va` / `timerchg.cir` | **§5** — a `timer` whose period changes fires at 1.5, 2.5, 3.5, 4.5 ms instead of 2, 3, 4, 5 ms |
| `flowonly.va` / `flowonly.cir` | **§5** — a flow-only `current` net contributed and read in one module is a singular matrix |
| `fmtwarn.va` | **§5** — lint L026 fires on a `%s` operand that is not the last argument |
| `hier.va`, `instarr2.va` | **§5** — `V(ra.p, ra.n)` and `arr[2].g` fail with unlocated internal errors |
| `badres.va` | **§7** — LRM 6.3.6's double-scaling module compiles silently (documented in the tracker, not a finding) |
| `instarr.va` | control — instance arrays work at run time (four instances draw 4 mA, plus two more at 2 mA each) |

## Decks that measured conformance

The controls named in the report's §6 (expression semantics, math functions, parameter
ranges, branches, user-defined functions, event timing, core and filter operators,
statements, hierarchy, analysis flags, plain-branch noise, file I/O, the OSDI knobs) were
run from the session scratchpad and are summarised in the report rather than kept here;
each is a one-module deck whose expected values are printed next to the measured ones in
the report's tables.
