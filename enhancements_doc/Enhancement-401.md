# Enhancement-401 — the short that was neither collapsed nor sourced

`V(a,b) <+ 0;` between two module **terminals** connected nothing at all. It is
the LRM's own way of writing "these two pins are the same node", and it silently
produced an **open circuit**.

The LRM's page-155 `parares` exists to demonstrate exactly that idiom — a
resistor that degenerates to a wire once `r` is small enough. Driving 1 V into
terminal `a` through 1 kΩ with terminal `b` loaded to ground through 1 kΩ, a
short gives −0.5 mA:

| `r` | branch taken | `i(v1)` before | after |
| --- | --- | --- | --- |
| `1e-6` | `V(a,b) <+ 0.0` | **0.0 — open** | **−5.00000e-04** |
| `1e-2` | `I(a,b) <+ V(a,b)/r` | −4.99998e-04 | −4.99998e-04 |
| `1.0` | `I(a,b) <+ V(a,b)/r` | −4.99750e-04 | −4.99750e-04 |

Crossing the model's own threshold flipped it from wire to open — the opposite
of what it says. Neither tool said anything.

The same shape sits in this project's own OSDI test model. `diode_lim.va` ties
its thermal terminal to ground with `Temp(br_sht) <+ 0` when `rth == 0` — the
**default**. Force 1 µA into that terminal and it read **1000 V** of self-heating
rise instead of 0.

## Two causes, neither wrong on its own

**`V(a,b) <+ 0` is not a residual contribution.** `hir_lower::stmt::contribute`
recognises a literal-zero potential contribution as a **node-collapse request**
and emits a `CollapseHint` callback; the value never reaches a residual.

**ngspice cannot honour that request for terminals.** `collapse_nodes`
(`src/osdi/osdisetup.c`) says so itself:

> Terminals can never be collapsed in ngspice because they are allocated by
> ngspice instead of OSDI.

Collapsing means "these two solver unknowns are one", which a device may say
about its own internal nodes but not about circuit nodes it does not own.

**And nothing replaced it.** `build_branch`'s potential arm builds no equation
for a trivial contribution unless the branch current is probed. So the collapse
was dropped by the simulator, no source was built by the compiler, and the branch
simply was not there.

It worked whenever *either* endpoint was internal — which is every production
compact model (BSIM4's `V(s,si) <+ 0`, `si` internal, collapses to exactly 0 Ω) —
and that is why it survived this long.

## The obvious fix is wrong, and the regression is what proves it

Building the 0 V source in the compiler and stopping there passes everything it
is aimed at: `parares` correct at both ends of its threshold, the p114 `relay`
unaffected, terminal-to-ground pinned, every internal-node collapse bit-identical,
`cargo test` 210/0.

**It also breaks five regression examples** — `dynmodels`, `electrothermal`,
`modelnoise`, `noisefigure`, `rfpa`.

**A 0 V source between two nodes the netlist has already shorted is singular.**
Node collapsing is idempotent; an equation is not. Measured both ways:

```
HICUM, thermal terminal grounded (N1 c b 0 0 0 — the normal wiring)
    Warning: singular matrix:  check node n1#xf1        (no result)
the same deck with that terminal on its own net
    onoise_spectrum[0] = 9.458517e-09                   (fine)

parares with both pins on one net
    Warning: singular matrix:  check node n1#flow(a,b)
```

The compiler cannot decide this. Whether the short is *needed* depends on the
netlist, and only the simulator knows the netlist. A compile-time diagnostic
fails for the mirror-image reason: it would fire on HICUM, DIODE and BSIMSOI,
where the netlist already grounds the terminal and nothing is wrong.

## So the fix is two-sided

**The compiler emits the 0 V source** for a branch whose endpoints are all
simulator-allocated, in both the constant-potential arm and the switch arm.
`parares` takes the *switch* arm: its condition is parameter-dependent, so
`is_voltage_src` is a runtime value while `op_dependent` is false, and the branch
had been dismissed as "just node collapsing".

**The compiler also says which branches those are**, so the simulator can undo
the equation when it turns out to be redundant. Two new exported symbols:

```
OSDI_TERM_SHORT_COUNTS   one count per descriptor
OSDI_TERM_SHORT_INFOS    { node_1, node_2, flow_node }
```

`node_1`/`node_2` are the shorted terminals (`node_2` is `UINT32_MAX` for a short
to ground) and `flow_node` is the branch-current unknown. This is the **additive**
extension pattern this project already uses for `absdelay` and `last_crossing`:
the `OsdiDescriptor` layout does not change and the ABI version does not move, so
an old simulator ignores the symbols and a new one uses them.

**ngspice drops the branch current** when the two terminals do not resolve to two
*distinct connected* circuit nodes — they are the same node, the short is to
ground and the terminal *is* ground, or an endpoint is not a connected terminal at
all (where the ordinary collapse already applies). The equation then survives
exactly when it is needed, and the singular row never forms.

The entry is only recorded for branches whose current the model never reads, and
that is what makes dropping it safe.

## What does not change

Terminal ↔ **internal** node still collapses, exactly as before, to exactly 0 Ω.
That is the path every real compact model uses, and turning those into equations
would add an unknown per collapsed node. The op-dependent switch branch (the LRM
page-114 `relay`) already built a real switch branch and is untouched.

## Verification

* **Full regression 322/322** — the five failures of the compiler-only attempt
  are gone.
* **`cargo test --workspace --features llvm18` 210/0**, with six snapshots
  regenerated; each shows a `collapsible` entry becoming a `flow(...)` unknown
  plus its equation, and the internal-node `collapsible (CI, C)` preserved.
* **Corpus differential** — 124 `VA_TEST` models, both binaries at the same `-o`
  path: **107 compiled by both, 0 return-code differences, 20 byte differences.**

**This is the first release in this run that changes emitted bytes, so the count
is the point rather than a footnote.** All 20 are thermal models — HICUM L0/L2,
HiSIM-HV, HiSIM-SOI, BSIM-BULK, BSIM-CMG, BSIM-IMG, ASM-HEMT, MVSG, MOSVAR —
every one of which ties a thermal *terminal* to ground when self-heating is
disabled. They correlate exactly with the new metadata: each changed model
exports `TERM_SHORT` symbols, and the 87 unchanged ones export none (psp103 and
bsimsoi: zero, because their collapses land on internal nodes).

The structure changes; the answers do not. HICUM L2 on a normally-wired circuit
gives **−1.86927e-02 on both binaries**, self-heating off and on.
