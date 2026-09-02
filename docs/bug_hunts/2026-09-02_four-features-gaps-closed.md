# Bug hunt — closing the gaps left open on autobus / autoadapt / osdimc / saveused

**Date:** 2026-09-02 · **Commit under test:** `b2e72a8f` · **Binaries:**
`ngspice-46/build/src/ngspice` and `OpenVAF-master-20260610/target/opt/openvaf-r`
as committed.

The [first hunt over these four](2026-09-02_autobus-autoadapt-osdimc-saveused.md)
ended with a table of what it had *not* tested. This pass goes at that table
rather than repeating the first sweep.

**Result: no new findings.** Every named gap was exercised and held. That is a
weaker headline than a bug but a real one: four surfaces move from "untested" to
"tested and sound", and the two known `saveused` defects are confirmed still
open.

| gap named in the first hunt | status now |
|---|---|
| **osdimc** trial-policy layer | closed by the [second hunt](2026-09-02_osdimc-trial-policy.md) — one finding, machinery sound |
| **autobus** `e449_expand_bus_port`, kicad spelling | **closed here — sound** |
| **autoadapt** `.adapt` node-list filter | **closed here — sound** |
| **saveused** × osdimc and the loop commands | **closed here — sound** |

---

## autobus: the subcircuit path is correct

`inp2n.c:183` flags `e449_expand_bus_port` in `subckt.c` as a **separate code
path** not covered by the expansion the first hunt tested. Exercised with
`busdev` (`inout [0:4] a`), whose bits carry conductances `r, 2r, 4r, 8r, 16r`
so any mis-binding is visible in the currents, each bit driven at a distinct
voltage:

```
flat      N1 p0 p1 p2 p3 p4 0 busdev
subckt    X1 p0 p1 p2 p3 p4 0 leg / .subckt leg a[0] a[1] a[2] a[3] a[4] b
                                    N1 a b busdev
```

Both give `i(v0..v4)` = −1.000, −1.000, −0.750, −0.500, −0.3125 mA,
**bit-identical**, and each matches its closed form (bit *k* sees *k*+1 V across
2^*k*·1 kΩ).

**The KiCad spelling works through the same path.** `.option autobus=kicad`
with `a_0_ … a_4_` formals returns the identical five currents — E-464's fix
(the spelling not reaching the flattener, leaving bits floating) holds.

**A descending `.subckt` declaration binds in reverse, by design.** Writing
`.subckt leg a[4] a[3] a[2] a[1] b` gives different currents, which is *not* a
defect: `subckt.c` documents that bits are emitted by ascending index while the
`.subckt` line's written order decides the port order — E-411's rule one level
up. The arithmetic confirms the intended mapping exactly: `a[1]←p4` gives
4 V / 1 kΩ = 4 mA, `a[4]←p1` gives 1 V / 8 kΩ = 0.125 mA, both observed. With
ascending formals the subcircuit form is bit-identical to the flat one.

## autoadapt: the `.adapt` filter reports what it cannot match

Whole-token matching and the unmatched-member report both work:

```
.adapt b            -> b split -> b_f (n1 port 1) / b_r (n2 port 0)
.adapt bb           -> Error: ... names 'bb', which is not a bus node shared by
                       two OSDI devices here; nothing was adapted for it.
.adapt nosuchnode   -> the same Error
.adapt b, nosuchnode-> adapts b AND names only the member that went nowhere
```

This is [Enhancement-467](../../enhancements_doc/Enhancement-467.md)'s fix
behaving exactly as its write-up describes.

**A near-miss worth recording.** This was very nearly written up as a finding.
An initial probe filtered ngspice's output with a grep pattern containing
`not adapted`; the actual message says *"nothing was adapted for it"*, so the
pattern matched nothing and the case looked **silent** — the same shape as the
`-inflate` defect E-538 had to fix. Reading E-467 before writing it up showed
the behaviour had already been found and fixed, and re-running without the
filter showed the error was there all along. The grep was the bug.

## saveused × osdimc and the loop commands: no interaction

`saveused` infers what to keep from the control block's text, so a loop command
whose metric it failed to save would read stale or fail. Differentially tested
on a deck with a discriminating spec (47.5 % yield, 21 violations — not a
degenerate all-pass):

| metric | without `saveused` | with `saveused` |
|---|---|---|
| `v(mid)` | 47.500 % (19/40), 21 violations | **identical** |
| `@mm[r]` | 47.500 % (19/40), 21 violations | **identical** |

Both metric spellings survive, the node reference and the `@dev[param]`
accessor alike.

## The two known `saveused` defects are still open

Re-verified against this commit; neither is fixed, both documented in the
[first hunt](2026-09-02_autobus-autoadapt-osdimc-saveused.md):

* **F1** — an implicit-all `write` pruned by a stray `print`: the raw file holds
  **2** vectors where it should hold 5.
* **F2** — a bare node name in a `let`: the deck still fails with
  *"vector a2 is not available"* under `saveused` and works without it.

---

## Coverage, honestly

* This pass closed the four gaps it set out to close, and found nothing wrong in
  them. A no-finding hunt is worth recording precisely so the next person does
  not spend the hour again.
* **What it did not do is fix F1 and F2.** They have now been confirmed open
  twice. The open question on F1 is a design one — whether "an output command
  naming no vectors means all" should override `saveused` in every case,
  including a `write` used as a mid-block checkpoint — which is why it has not
  simply been patched.
* Nothing here re-examined the areas outside these four features; the
  [previous hunt's](2026-09-02_osdi-untouched-areas.md) list of untouched
  ground — node collapse, temperature, AC and noise, terminal currents, the
  solver layer — is unchanged.
