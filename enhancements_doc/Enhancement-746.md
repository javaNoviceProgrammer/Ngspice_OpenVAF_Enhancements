# Enhancement-746: a native `nport` instance no longer prints 509 unconnected-terminal warnings — a device whose terminal count is a maximum carries `DEV_VARTERMS`, the dispatcher names and grounds nothing above the line's count, and the device's own setup message gives the counts

**Scope:** F6 of the
[Touchstone-import hunt](../docs/bug_hunts/2026-09-26_touchstone-import.md).
`src/include/ngspice/devdefs.h` (the flag), `src/spicelib/devices/nport/nportinit.c`
(the device carries it), `src/spicelib/parser/inp2n.c` (E-481's warning and
the `silentports=ground` binding skip a flagged device),
`src/spicelib/devices/nport/nportsetup.c` (the short-line message names both
counts), `examples/nport_native_examples/` (three checks),
`examples/crashfix2_examples/` (its E-244 check reads the new wording).
**ngspice only.**

**Suites:** [`nport_native_examples`](../examples/nport_native_examples/) 9
of 9 per solver, both solvers (7 of 9 on the E-745 binary); `crashfix2`
re-pinned to the new message; `silentports`, `groundports`, `dcpath`,
`presnp` unchanged; full sweep 532 of 532.

## What was wrong

The native n-port device (E-242) declares `NPORT_MAXTERMS` = 512 terminals,
because its port count is only known from the model's fit file and the
generic `N` dispatcher sizes the node array from the device's declared
count. E-481's warning compares the instance line's node count with that
declared count, so every `N1 p1 p2 0 mm` printed

```
Warning: instance n1: 509 of the 512 terminals of model type 'nport' are not connected.
         terminal 4 ('4') is absent
         ...
         terminal 512 ('512') is absent
         The model sees $port_connected() = 0 for these, and any branch
         to them carries no current. They are NOT grounded -- connect
         them to 0 explicitly if that is what you meant.
```

on every instance — 510 lines on the suite's own one-port deck — with a
closing sentence written for compiled modules that means nothing here. Under
`.option silentports=ground` (E-482) the dispatcher went further and bound
the 509 phantom terminals to node 0. And the message that does matter, the
device's own refusal of a line with too few nodes, said *connects fewer
nodes than the 2-port model needs* without saying how many it connected.

## What changed

A device flag, `DEV_VARTERMS`, says that `terms` is a maximum: an instance
declares its own terminal count by the nodes on its line. The native n-port
carries it. In the dispatcher, the E-481 warning and the `silentports=ground`
binding both skip a flagged device, so nothing above the line's count is
named or grounded; the terminals stay unbound (−1) as they were under the
default mode, which is what the device's setup expects. An OSDI device is
not flagged, and E-481's behaviour there is untouched — a short line on a
compiled module still names each absent terminal, and E-719's hold still
follows.

The device's setup message now carries both counts:

```
nport: instance 'n1' connects 1 node where the 1-port model 'rcm' needs 2 (1 port + the reference)
```

## Verification

Three checks in `verify_nport_native.py`, no compiler, both solvers:

* the suite's RC one-port line draws no unconnected-terminal warning and no
  absent-terminal list, and its point is unchanged;
* a line that is short — the one-port without its reference — gets the
  device's message with the counts and no terminal list;
* under `.option silentports=ground` the deck runs and the point is
  unchanged, the phantoms not bound to node 0.

On the E-745 binary the first two fail (510 warning lines; the old wording);
the third passes there too, since grounding the phantoms had not changed the
point — it pins that the new path is equivalent. The `crashfix2` suite's
E-244 check, which pinned the old wording, reads the new one and keeps
accepting the old. `silentports` (24), `groundports` (59), `dcpath` and
`presnp` are unchanged.

## What this does not do

* The flag marks one device. No other built-in declares a maximum, and OSDI
  devices declare their exact port count, so nothing else changes.
* A native n-port line with *more* nodes than its model's ports is not
  refused: the extra nodes are bound and ignored by the stamp, as before.
* The generic node array is still sized to 512 per instance; the flag is
  about messages and binding, not memory.
