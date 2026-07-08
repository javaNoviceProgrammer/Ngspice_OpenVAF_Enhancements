# Enhancement-93 — warning when a fixed (localparam) parameter is set

Enhancement-92 froze structural width parameters to `localparam` so a netlist
override could no longer corrupt the model. But the override was still
**silently ignored** — openvaf exports every `localparam` as an OSDI
parameter (its slot stores the computed value), so ngspice recognised the
name, accepted the assignment, and dropped it with no feedback. Enhancement-93
makes that override an explicit warning.

## The change (openvaf + ngspice)

**openvaf** marks each non-settable parameter in the OSDI descriptor. A new
additive flag bit, `PARA_FLAG_FIXED` (`1 << 2`, a free bit of the parameter
`flags` field), is set for every `localparam` — which includes the structural
width parameters frozen by Enhancement-92. Being additive, it does not change
the descriptor layout or the ABI; a simulator that does not know the bit
simply ignores it.

**ngspice** checks the flag where a model/instance parameter is applied
(`OSDIparam`/`OSDImParam`, `src/osdi/osdiparam.c`): if the target parameter
carries `PARA_FLAG_FIXED`, it emits

```
Warning: parameter 'N' is a fixed (localparam) value and cannot be set from
the netlist; ignored.
```

and skips the write (which was overwritten by the parameter-init default
anyway). Ordinary parameters are unaffected.

This turns the silent no-op into clear feedback, and it generalises correctly
to *all* localparams, not just frozen width parameters — a `localparam` is
non-overridable by definition (LRM), so setting one from the netlist is always
a user error worth reporting.

## Verification

`paramnonset_examples` (7/7, ngspice runtime pins):

- overriding the frozen width parameter `N` (`.model ws wsum N=8`) now
  **warns** and keeps the default (`v(s)=2.08333`, the value that
  Enhancement-92 already made correct);
- overriding a hand-written `localparam` (`scale`) also warns and keeps its
  default;
- overriding an ordinary parameter (`gain`) does **not** warn and **does**
  take effect (`v(s)=6.25`).

Full regression: 84 verify suites + 28 integration tests (the OSDI descriptor
snapshots were regenerated — only `hisimsotb`, which exports a localparam,
gained the flag). The additive flag keeps every other descriptor byte-identical.
