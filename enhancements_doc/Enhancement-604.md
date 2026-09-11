# Enhancement-604: a numparam failure refuses the line, or the deck — not the process

**Scope:** `src/frontend/numparam/spicenum.c` (`nupa_eval`: a card's failure attached
to the card; `nupa_done`: the deck refused instead of `exit(1)`), `numparam/xpressn.c`
(`message`: the sink, the line labels; the empty-expression message), `numparam/numparam.h`
and `numpaif.h`, `src/include/ngspice/inpdefs.h` (`struct card.nupa_error`),
`src/frontend/inp.c` (the error folded in after the parse, the whole message printed, a
`.model` card's numparam failure an error), `src/frontend/subckt.c` (the deck refused;
`nupa_error` copied with a card), `examples/nupafail_examples/` (new, 13 checks per
solver). **ngspice only; numparam serves every device.** Finding N5 of the 2026-09-10
integration hunt
([`docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md`](../docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md)),
a stock ngspice defect.

**Suites:** [`nupafail_examples`](../examples/nupafail_examples/) 13 of 13 per solver,
both solvers; `hunt3diag`, `helpcmd`, `osdisens` (the suites that read numparam's
messages) unchanged; full sweep 502 of 502 (one sweep, Enhancements 604–608 folded
together).

## What was wrong

```
r1 in out 1k w=nan
```

```
Error in netlist line no. 4, new internal line no. 3:
Undefined parameter [nan]
Error in netlist line no. 4, new internal line no. 3:
Cannot compute substitute: 'nan' is not a .param name; ...
ERROR: fatal error in ngspice, exit(1)
```

`w=nan` — and a trailing `w=`, read as `{}` — reaches numparam as a brace expression it
cannot evaluate, and every numparam error ended the **process** at `nupa_done()`: in
batch, and in an interactive session, where `source` of such a deck took the session
and everything loaded before it. `w=1e400` on the same line is refused at the line
level ("Error on line 3 or its substitute", the run interrupted, the session alive).
Two smaller things sat beside it: numparam's message printed the internal line number
as the netlist's and the netlist's as the internal one (`srcline`/`oldline` under each
other's label — line 3 of the deck was "netlist line no. 4"), and `inp_dodeck` printed
only the **first line** of a card's error text, returning before the rest.

## What changed

- **A failure on a device, model or dot card refuses the line.** `nupa_eval` collects
  numparam's message in a sink instead of stderr, attaches it to the card as
  `nupa_error`, and hands the line on in the author's own text (`w={nan}`, not a
  half-filled placeholder). `inp_dodeck` clears `error` before it parses — a re-parse
  must not report a previous pass's messages — so the new field survives that and is
  folded in after the parse, ahead of what the parser made of the unevaluated text:

  ```
  Error on line 3 or its substitute:
    r1 in out 1k w={nan}
  numparam: Undefined parameter [nan]
  Cannot compute substitute: 'nan' is not a .param name; if it is meant as a string value, quote it: "nan"
    parameter 'w': '{nan}' is not a number
      Simulation interrupted due to error!
  ```

  The card's error guarantees the refusal whatever the parser does with the text — a
  `{nosuch}` in a **node** position would otherwise be taken as a node name. A `.model`
  card's numparam failure is an error, not the "Model issue" warning a model card's
  other complaints are, which would have run the model on the parameter's default.
- **A failure elsewhere refuses the deck.** A `.param` line, a `.func`, a subcircuit
  call's value: `nupa_done` returns the verdict, `inp_subcktexpand` returns NULL as it
  does for an unknown subcircuit — "Numparam expansion errors in the netlist's .param,
  .func or subcircuit lines (see above): the circuit is not loaded." — and the batch
  run exits 1 as any refused deck does; the terminal's "Run Spice anyway? y/n" is kept,
  its `n` refusing rather than exiting.
- `w=` with nothing after it: "the value is missing — nothing follows the '=' (or the
  braces are empty)" in place of "Expression err: }".
- The line labels are the right way round; the whole error text is printed.

## Verification

| check | before | now |
|---|---|---|
| `r1 in out 1k w=nan`, batch | "fatal error in ngspice, exit(1)" | "Error on line 3 or its substitute", the line, numparam's reason and the parser's message; exit 1 |
| a trailing `w=` | the same, "Expression err: }" | refused; "the value is missing -- nothing follows the '='" |
| a session sourcing the bad deck | the session dies | "still-alive"; the previous circuit answers 0.5 V |
| `.param k = nosuch + 1` | fatal | "the circuit is not loaded"; the session alive; batch exit 1 |
| a subcircuit call's `p={nosuch}` | fatal, "netlist line no. 8" | refused; "netlist line no. 6" |
| `{nosuch}` in a node position | fatal | refused as a line |
| `.model rm r r={nosuch}` | fatal | an error on line 5, not a model-issue warning; no run |
| `v1 in 0 dc {nan}` | fatal | refused as a line |
| a deck whose braces evaluate; `w=1e400` | runs; refused | unchanged |
| an OSDI line with `w=nan` | fatal | the same line-level refusal |

Full sweep 502 of 502 on both solvers.
