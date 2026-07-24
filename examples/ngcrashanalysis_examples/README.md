# Analysis crash-hardening — `.tf` / `.pz` / `.disto` (Enhancement-315)

Three hard crashes in the shipped ngspice, found by command/netlist fuzzing (the
[E-222](../../enhancements_doc/Enhancement-222.md)–228 / [E-270](../../enhancements_doc/Enhancement-270.md)–285 family). Each is now a clean error.

- **[6] `.tf` on a singular circuit** (dangling inductor) → SIGABRT. `tfanal.c` ignored `CKTop`'s
  return, so `SMPsolve` asserted `IS_FACTORED` on an unfactored matrix. Fixed: propagate the error.
- **[7] second `.pz` over a URC device** → SIGSEGV. `CKTic` zeroed a NULL `CKTrhs` (the loop
  vectorises to `memset`). Fixed: return cleanly when the RHS vectors are unallocated.
- **[8] `.disto` with no distortion sources** (a plain resistor) → SIGSEGV. `distoan.c`'s output
  section left `OUTpBeginPlot`'s result unchecked, so `OUTattributes(NULL, …)` crashed. Fixed:
  check the result and bail.

Legitimate `.tf`/`.pz`/`.disto` are unaffected — the guards fire only on the failure paths.

## Verify

```sh
python3 verify_ngcrashanalysis.py
```

Four checks: each of the three decks crashed the pre-fix binary and now exits cleanly, plus a
forward guard that a legitimate `.tf` still computes the correct transfer function (0.5).
