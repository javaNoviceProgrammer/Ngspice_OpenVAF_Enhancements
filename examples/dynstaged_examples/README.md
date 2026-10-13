# dynstaged_examples — Enhancement-876

[E-876](../../enhancements_doc/Enhancement-876.md): F3 of the
[transient stress campaign of 2026-10-12](../../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

TR-BDF2 sets the order to 2 at the start of every step and SDIRK to 3. `dynorder` re-decided the
order after each accepted step; when a neighbouring order allowed a bigger step it changed the
order, and its rule is not to grow the step in the step that changes the order. The staged method
reset the order at the next step, so the step never grew: a capacitor that never moves took
10 002 points under `sdirk dynorder` where `sdirk` takes 16, and runs with a small first step
never ended. `dynorder` now leaves the staged methods alone, and says so.

The checks:
- **[1]** A sine into an RC: `trbdf2` with `dynorder` runs point for point as `trbdf2`.
- **[2]** A capacitor that never moves: `sdirk` with `dynorder` runs as `sdirk`.
- **[3]** A 48 ns network of the campaign, with a 2e-14 s first step, under `sdirk maxord=4
  dynorder` ends within 20 s.
- **[4]** A note says `dynorder` has no effect with `trbdf2` and with `sdirk`.
- **[5]** (control) `dynorder` still takes Gear above order 2 on the RC.

Run: `python3 verify_dynstaged.py` (5 checks per solver). On the E-875 binaries [1] to [4] fail.
