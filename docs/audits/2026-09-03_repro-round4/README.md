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
| `swnoise2.va` / `swnoise2.cir` | **§3** — a noise-only `V(p,n) <+ white_noise(...)` in the arm after a flow contribution is dropped (only the load's `4.07e-9` remains); `swnoise.va` with `sw=1` is the control that works. **Fixed** (the noise-only rule from E-531 asked a monotonic place lookup, so one `if` arm's classification made its sibling look classified; it is now path-sensitive) — the deck prints the LRM's `1e-6` on the fixed pair and reproduces only against the audited binaries. Pinned by five new checks in `examples/lrmnoise_examples/` |
| `swnoise.va` / `swnoise.cir` | **§3** — flow-arm noise on a switch branch with netlist `m=9` reads `2.7e-3` instead of `3e-4`; the same module wrapped with `#(.$mfactor(9))` is right. **Fixed** (a switch branch injects every source into its branch-current equation, whose node coupling already carries `$mfactor`, so the arm must not take √m a second time; `ac_stim` takes no factor at all) — the deck prints `3e-4` on the fixed pair and reproduces only against the audited binaries. Pinned with the finding above |
| `icint.va` / `icint.cir` | **§7, WITHDRAWN** — `.ic v(n1#mid)=0.2` under `uic` has no effect on the OSDI internal node. Reproduces, but is **not a defect**: ngspice resolves `.ic`/`.nodeset` node names in parser pass 3, before any device setup creates internal nodes, so a built-in BJT's `q1#collector` is refused the same way — with a named warning on both routes. OSDI honours `.ic` wherever any device can (a Verilog-A `ddt` holds a seeded external node exactly as a built-in capacitor does) |
| `strrep.va` | **§3, §4** — line 6: `"hello\0world"` prints `hello`; line 17: `{i{"Hi"}}` is refused (LRM 3.3 marks it OK). **Line 17 fixed** (an integer-typed runtime multiplier now lowers to an append loop over the once-evaluated unit); the deck's replication line compiles clean on the fixed compiler and reproduces only against the audited binaries. Pinned by four new checks in `examples/lrmdata_examples/` |
| `hexlit.va` | **§4** — `32 'h 12ab_f001` (LRM 2.6.1 Example 5), `'h 1f`, `'h 1e5` are lexed as real numbers. **Fixed** the same day (a lexer digit-run mode after a bare base token, plus the parser accepting macro-substituted number tokens as digits); the deck compiles clean on the fixed compiler and reproduces only against the binaries the audit measured (`04e42be2`). Pinned by four new checks in `examples/lrmlex_examples/` |
| `nullarg.va` | **§4** — null arguments to `cross`/`above`/`timer` (LRM 5.10.3.1's sample-and-hold) are a type error. **Fixed** (a null optional argument now lowers to "not specified", identical to the trailing omission); the deck compiles clean on the fixed compiler and reproduces only against the audited binaries. Pinned by four new checks in `examples/lrmevents_examples/` |
| `macroq.va` | **§4** — the `` `" ``, `` `\`" `` and ``` `` ``` macro operators are lexer errors. **Fixed** (lexed as operator tokens inside define bodies, interpreted at expansion; synthesized text lives in a preprocessor-flushed virtual file, so spans resolve normally); the deck compiles clean on the fixed compiler and reproduces only against the audited binaries. Pinned by three new checks in `examples/lrmlex_examples/` |
| `incline.va` + `inc/sub2.vah`, `incline.cir` | **§4** — `` `__LINE__ `` inside an included file is refused. **Fixed** (both macros now expand in the preprocessor at the position of use, so the include reports its own file and line and the root file resumes after it); prints `line=3 file=sub2.vah` then `line=5` on the fixed pair |
| `linedir.va` / `linedir.cir` | **§4** — `` `line 500 "fake.va" 0 `` has no effect on `` `__LINE__ ``/`` `__FILE__ ``. **Fixed**: prints `line=500 file=fake.va` (500, not the audit annotation's 501 — IEEE 1364 19.7 says the number names the NEXT line, and the use sits on it; the deck's comment is corrected). Pinned with the include scoping by six new checks in `examples/lrmlex_examples/` |
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
