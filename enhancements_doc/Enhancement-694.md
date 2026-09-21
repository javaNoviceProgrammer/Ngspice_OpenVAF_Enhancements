# Enhancement-694: `--dump-json` escapes its strings — a `$fatal`'s message ends in a newline, and every module with a message task dumped invalid JSON

**Scope:** F4 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_openvaf-r-cli-integers-transition-and-json.md).
openvaf: `mir/src/serialize.rs` (`json_escaped`, applied to every string the
dump writes: the string constants, the input names, the keys).
`examples/hunt13slips_examples/` (one check added, 8 per solver).
**openvaf only.**

**Suites:** [`hunt13slips_examples`](../examples/hunt13slips_examples/) 8 of 8
per solver, both solvers (the new check fails on the E-692 binaries); the
compiler workspace tests green apart from the three pre-existing sourcegen
drift failures; full sweep 531 of 531.

## What was wrong

`openvaf-r m.va --dump-json --dry-run` on a module containing
`if (V(a,b) > 100) $fatal(1, "too much: %g", V(a,b));` wrote `m_m.json` that no
JSON parser accepts ("Invalid control character at line 226 column 36"): the
value entry read

```
{
    "sconst": "too much: %g
    ",
    "uses": [ 89 ]
}
```

with a real newline inside the string. `$fatal` with or without a message
(`"$fatal\n"` for the message-less form), `$error`, `$warning` and `$info` all
did it — which is every production compact model, since each carries at least
one of those. `$strobe("a\nb")`, `$display`, `$finish`, a `string` variable
holding `"x\ty"`, a literal with `\"` and the noise source names produced valid
files, by luck: the lexer keeps a source escape as the two characters `\` `n`,
which happen to be valid JSON.

Two things met. `hir_lower/src/ctx.rs` (`runtime_fatal`) builds the run-time
message as `format!("{msg}\n")` — a real newline, since it goes to `printf` —
and `mir/src/serialize.rs` wrote every string constant as
`"sconst": "<raw>"`, with no escaping at all, so any control character, `"`
or `\` in an interned string broke the file. [E-640](Enhancement-640.md)
implemented the dump and its own check used a module without a message task.

## What changed

**Every string the dump writes is a JSON string.** `json_escaped` produces the
body of a JSON string literal per RFC 8259 §7: `"` and `\` backslash-escaped,
the control characters as `\n`, `\t`, `\r`, `\b`, `\f` or `\u00XX`, everything
else as is. It is applied to the string constants (`"sconst"`), to the input
names (`"parameters"`, `"voltages"`, … entries) and to every key, including
the output names. The lowering is untouched: the run-time message keeps its
newline, and the dump now says so as `"too much: %g\n"`, which a parser reads
back as the string the model prints.

## Verification

| check | result |
|---|---|
| a module with `$fatal(1, "…%g", x)`, `$error`, `$warning`, `$info`, `$fatal(0)`, a `\"` and a `\t` literal, `--dump-json --dry-run` | `json.load` succeeds (was "Invalid control character") |
| the five message constants read back | `"too much: %g\n"`, `"e %g\n"`, `"w\n"`, `"i\n"`, `"$fatal\n"` — each with its newline |
| the hunt's eight-variant bisection (`p66b.py`, `p66c.py`) and its two full modules (events, noise, four delay operators, a Laplace filter) | valid, all |
| a module without a message task (E-640's own check) | unchanged |
| the E-692 binaries on the suite | the new check fails per solver |
| workspace tests; full sweep | green apart from the sourcegen drift; 531 of 531 |

## What this does not do

- The dump's *content* — the cfg, the instructions, the outputs — was not
  cross-checked against the MIR beyond validity; that is E-640's ground.
- A source literal's escape stays the two characters the lexer kept
  (`"x\ty"` dumps as `"x\\ty"`), which is what the interned string holds; the
  dump reports the MIR, not the printf output.
- The run-time message format is unchanged; only its serialisation is.
