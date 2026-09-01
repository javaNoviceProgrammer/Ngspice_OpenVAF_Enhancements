# huntfix2 — the openvaf-r hunt round, pinned

Regression suite for the fixes from the 30-minute openvaf-r adversarial hunt
(Enhancement-532). One verify script, both solvers, 21 checks.

| File | Pins |
|---|---|
| `hxshort.va` | **H2, the headline**: a terminal-to-terminal short spelled through a chain of collapses (`V(a,m)<+0; V(m,b)<+0`) used to be a silent **open circuit**, while the direct `V(a,b)<+0` spelling shorted correctly through E-401's 0 V source. The simulator now stamps a synthetic ideal 0 V source for every collapse merge the node mapping cannot honour — checked in op, AC, transient, across `reset`, and through `sens`'s double-setup path. |
| `hxcollapse.va` | The other merge shapes the old collapse loop got wrong: a terminal-to-**ground** chain (dropped the same way), a ground-collapsed group merged again (used to quietly un-ground it), and a collapse **triangle** (a redundant hint used to corrupt the node count). |
| `hxrange_bad.va` / `hxrange_ok.va` | **H3**: a constant parameter default that violates its own constant range earns the new `param_default_out_of_range` lint (L027) — one warning per offending parameter, none for in-range defaults, none for the `(* openvaf_allow *)`-silenced must-give idiom, none where the default is not a compile-time constant. |
| `hxnoisedrop.va` | **H1**: opposite-kind noise on a classified branch — the E-400 report now states the discarded site is *noise-only* (it never decides the branch kind, but its noise vanishes with the losing kind), and the run pins that the output noise really is the source resistor alone. |
| `hxcorr.va` | **H5, a retraction pinned**: noise correlation follows the *call*, not the label (LRM 4.6.4.6, E-528). Separate same-labelled calls sum as powers (2S), one call's output reused sums as amplitudes (4S), a scaled call scales power quadratically — all against closed-form spectra, so the audited semantics cannot regress silently. |
| `hxlimexp.va` | **H4**: the documented `limexp` knee — exactly `exp` at x = 68, exactly the tangent line `1e30·(1 + x − ln 1e30)` at x = 80 — so handbook §4.4 cannot drift from the implementation. |

Run it:

```bash
python3 verify_huntfix2.py
```
