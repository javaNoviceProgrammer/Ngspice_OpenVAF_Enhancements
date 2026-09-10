# `.option dcpath` — operating-point robustness, and an improvement plan

**Date:** 2026-09-10, about fourteen decks beyond the 37 checks of `dcpath_examples`,
both solvers where a value was compared. **Rule:** probe, record, plan; nothing was
changed. Every deck is in the scratchpad (`dcp/`). The question asked was how robust the
operating point is under Enhancement-575's topology check, so the probes went after the
surfaces the write-up does not pin: the analyses with a load path of their own, the
hierarchy, re-setup, the OSDI collapse, scale, and the three limits the write-up names.

**Toolchain:** commit 2ceda751 (after E-594), `ngspice-46/build/src/ngspice` and
`OpenVAF-master-20260610/target/opt/openvaf-r` as built.

## Verdict

The numerics are robust: every probe converged and gave the right value, and nothing
the hold touches was distorted. What is left is on the **diagnosis** side — one false
alarm, one knowingly unheld shape, one design choice that costs accuracy in a long
transient, and a cosmetic repetition — and each has a bounded fix. The plan below
ranks them.

## What was probed

| # | probe | result |
|---|---|---|
| 1 | `pz` on a capacitor-coupled node (`r1 in a 1k`, `c1 a g 1n`, `c2 g 0 1n`) | runs; the pole is −2·10⁶ rad/s, the exact 1/(R·C_series) — the hold does not distort `pz` |
| 2 | `sens v(g)` on the same | runs (the missing `v(g)` afterwards is the sens plot's own vocabulary, not a hold problem) |
| 3 | `disto` and `tf` on the same | both run; `tf` gives 0, right for a DC-blocked node |
| 4 | the floating node inside a subcircuit, two instances | both named with their full names, `x1.n` and `x2.n` |
| 5 | three levels deep | `xt.xb.xc.n` named |
| 6 | `.nodeset`, `.ic` and `tran … uic` on the held node | the op ignores neither; `uic` starts the node at 0.7005 V as written |
| 7 | `op`, `alter r1`, `op`, `reset`, `op` | the list is rebuilt at every setup, values stable |
| 8 | a node touched only by a VCVS's **controlling** pair and a capacitor | named — a control pair is a probe, as E-575 says |
| 9 | BSIM4 with `igcmod=1 igbmod=1`, gate driven only through a capacitor | the gate is **still named and held** — the table excludes a gate whatever the model card says (the hold is harmless: gmin is far below any modelled leakage) |
| 10 | an OSDI model with a collapsible internal node (`V(a,ai) <+ 0` when `r = 0`, else a resistor), a port reached only through it | silent in both states, 0.5 V and 0.4975 V as expected |
| 11 | a chain of 20 000 capacitor-only nodes | five named, "and 19995 more", the whole run in 0.08 s |
| 12 | a held node beside a diode chain that needs gmin stepping | converges normally; the hold is a fixed conductance added after the device loads and does not interact with the ladder |
| 13 | a five-pass `alter` loop with `op` | the warning is printed **five times** |
| 14 | the two-`ddt`-in-series internal node of the 2026-09-07 hunt | still singular at the op and left so — the documented internal-node rule |

Not re-probed, taken from the write-up and the 2026-09-07 hunt: the thermal-port
ambiguity (a pure power source looks like a thermal resistance in the Jacobian pattern
and is left singular), `rshunt` standing the walk down, and the message cap.

## What to leave alone

- **The thermal port.** Installing gmin there would "solve" the node at P/gmin, about
  10⁹ K. Naming it and stopping is right; the fix belongs in the model.
- **Types outside the table join every terminal** (lossless and lossy lines, coupled
  lines, URC's expansion). That errs toward silence: a floating node behind a line would
  be missed, never misheld, and the run behaves as it did before E-575. Refining the
  table for lines is item 5 below, and optional.
- **`rshunt` stands the walk down.** With a conductance on every node nothing lacks a
  path; the global workaround keeps its own numbers.

## The plan

Ranked by what a user gains. Effort is a day or less for each of 1, 2, 3 and 6, and two
to three days for 4; 5 is optional.

### 1. Release the hold outside DC — `dcpath=dc`, and consider it as the default

**What.** In a transient the capacitor companion conductances, 2C/h, are many orders
above gmin, and in AC the node sees jωC; a capacitor-coupled node is non-singular in
both. The hold is needed only where the matrix is evaluated at DC: `op`, `dc`, the
transient's initial operating point (`optran` included), the AC's operating point. Held
for the whole run, the node leaks with C/gmin — 2 pF against 1 pS is a two-second time
constant, pinned in `dcpath_examples` [4] as 1.5 V falling to 1.1682 V at 0.5 s. That is
Spectre's behaviour too, but it is the one place the feature changes a **result**, not a
message.

**Where.** `CKTdcpathStamp` (`cktsetup.c`), called from `CKTload` and `CKTacLoad`. Add
a mode flag on the circuit; under `dcpath=dc` the stamp returns early unless
`ckt->CKTmode` carries `MODEDCOP`, `MODEDCTRANCURVE` or `MODETRANOP`, and `CKTacLoad`
skips it. `dcpath_mode` learns the word `dc`.

**Verification.** [4]'s deck under `dcpath=dc`: flat at 1.5 V; the op values of every
[1] shape identical to `dcpath=gmin`; the AC divider of [5] still 0.5; `optran` on a
held node still three iterations. Then the question of the default: the suite's [4]
leak check is the only thing that pins `gmin` as the default's transient behaviour, so
flipping it is a one-line change in the suite and a paragraph in the write-up. My
recommendation is to add the mode first and flip the default in a second enhancement
once the sweep has run with it for a while.

**Risk.** Low. A node held at DC and released in tran starts the transient from a
consistent op and keeps it; nothing else reads `CKTdcpathG`.

### 2. A MOSFET gate with a gate-current model is connected

**What.** Probe 9: the table excludes any terminal whose name contains "gate", so a
BSIM4 with `igcmod` or `igbmod` on is named and held although its gate conducts. The
hold is numerically harmless; the warning is a false alarm on exactly the decks whose
authors know their gates leak.

**Where.** `dcpath_builtin_edges` decides `DCP_NOGATE` per type. Add an optional
per-model hook on `SPICEdev`, say `int (*DEVdcGateConnected)(GENmodel *)`, NULL for
every type (the tables use designated initialisers, so no device file changes for the
types that keep the capacitive reading) and implemented for `bsim4`, `bsim4v5`,
`bsim4v6`, `bsim4v7` and `bsimsoi` as `igcMod || igbMod`. When it answers yes the
instance's gate joins the other terminals. The other levels with a gate-leakage switch
(HiSIM's `coiigs`) can follow the same hook.

**Verification.** Probe 9 silent with the switches on and named with them off; the values
unchanged either way; `dcpath_examples` [1]'s MOS1 gate on a capacitor still named.

**Risk.** Low. Only the yes answer changes anything, and it only removes a hold.

### 3. Say it once per topology

**What.** Probe 13: an `alter` loop of a hundred passes prints the warning a hundred
times, because every `alter` re-runs setup and the walk. The first pass has already
named the nodes.

**Where.** `dcpath_check` frees and rebuilds `CKTdcpathNodes`. Keep the previous list
(count and node numbers) on the circuit across the rebuild; when the new list is
identical, print one line — "no DC path: the same N node(s) as before; gmin still
installed" — or nothing under the quiet default and the full report under `ngdebug`.
`reset` reloads the circuit, so it reports in full again, which is right.

**Verification.** Probe 13's loop prints the full report once and the terse line four
times; a loop whose `alter` changes the topology (an `altermod` switching a B-source
between voltage and current type) reports in full again on the pass that changes it.

**Risk.** Cosmetic. The `dcpath=error` mode must keep refusing on every pass.

### 4. An OSDI internal node reached only through reactive entries is not "reached"

**What.** Probe 14 and the 2026-09-07 hunt: two `ddt` contributions in series through an
OSDI internal node leave that node singular at the op, and the run falls through gmin
and source stepping to the transient-based operating point. The walk's rule that a
device-internal node counts as reached exists because the built-in table cannot see
inside a device; for an OSDI model the Jacobian pattern **can**, and it already supplies
the edges for the ports. The rule should not override what the pattern says about an
OSDI internal node.

**Where.** `dcpath_check`'s internal-node test, and `OSDIdcpathEdges` (`osdisetup.c`).
The OSDI setup records each instance's internal node numbers (E-351 keeps them for
reuse); pass that set to the check so those nodes are judged by the walk alone.

**Verification.** The hunt's two-`ddt` model: the internal node named and held, three
iterations, the AC value unchanged at −18.85 µA; the thermal internal node of [7] with
its own `rth` still silent; the collapsed node of probe 10 still silent in both states;
a `V(x) <+` branch to an internal node still joined through the branch rule.

**Risk.** Medium. Collapsed internal nodes and E-402's node for an omitted thermal
terminal both touch this path, which is why the three silent cases above are part of
the acceptance, and why this is the one item I would run the newton-phase suites
(`warmstart`, `failacct`, `linesearch`) on first.

### 5. Lines in the table (optional)

**What.** A lossless or lossy line is a DC path **along** each conductor, not across a
port. `DCP_ALL` joins all four terminals, so a node whose only element is a line's far
end is taken as reached. Analysis says such a node is in fact determined by the line's
equations, so no probe has shown a miss; this is a refinement of the reading, not a fix.

**Where.** A `DCP_ALONG` kind joining terminals 1–3 and 2–4 for `Tranline`, `LTRA`,
`TXL`; `CPL` per conductor. Do it only with a check per type in the suite, and drop it
if any type's DC behaviour is not the pairing.

### 6. Pin what the probes found, whatever else is done

Add to `dcpath_examples`: `pz`, `tf` and `disto` on a held node (the pole value);
a three-level hierarchy name; `alter` then `reset`; the OSDI collapsible node in both
states; the 20 000-node chain under a time bound; and the loop repetition count as it
stands, so item 3 has a number to change. Cheap, and it turns this hunt's evidence into
a regression guard.

## Order

6 first, since it costs an hour and protects the rest; then 1 and 2 as one enhancement
(both are per-mode or per-model refinements of what is installed and said), 3 as a
second; 4 on its own with the newton-phase suites run first; 5 only if a deck asks
for it.
