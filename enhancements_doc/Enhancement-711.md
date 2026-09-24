# Enhancement-711: the parser's step guard counts lookahead steps since the last consumed token — it counted them over the whole parse, so a legal file of about two million tokens was cut off in mid-file with "unexpected token EOF" at a line that has no syntax error

**Scope:** F3 of the
[robustness campaign of 2026-09-23](../docs/bug_hunts/2026-09-23_openvaf-r-robustness-campaign.md).
**Compiler only.** `parser/src/parser.rs` (`PARSER_STALL_LIMIT`, `Parser::nth`,
`Parser::do_bump`). [`examples/vafcrash2_examples/`](../examples/vafcrash2_examples/)
(3 checks, 22 in all). The hunt page.

**Suites:** `vafcrash2` 22 of 22 (20 of 22 on the E-709 binaries), `langguard`
132 of 132, `cubic_table`, `lrmkernel`, `lrmfilters` and `vafinstcheck` unchanged; the
compiler workspace tests green apart from the three pre-existing sourcegen drift
failures (221 passed), no build warnings; full sweep 532 of 532, run alone.

## What was wrong

One module whose analog block is n copies of `s = s + 1.0e-3 * V(p,n);`:

| statements | size | tokens | before | now |
|---|---|---|---|---|
| 100 000 | 2.5 MB | 1.3 M | compiles, 9.6 s | compiles |
| 140 000 | 3.5 MB | 1.82 M | compiles, 17.2 s | compiles |
| 150 000 | 3.8 MB | 1.95 M | `error: unexpected token EOF; expected 'root' or identifier` at line 147 048 | compiles, 21.8 s |
| 400 000 | 10 MB | 5.2 M | the same error at line 147 048 | compiles, 144 s, 5.6 GB |
| 340 000 of `s = s + 1.0;` | 4.4 MB | 2.4 M | the same error at line 333 301 | compiles, 1.6 s |

The boundary followed the token count, not the byte count: 147 047 × 68 and
333 300 × 30 are both ten million less the header, at 68 and 30 lookahead steps per
statement. Enhancement-220's guard against a parser spinning in error recovery counted
every `nth()` lookahead call over the whole parse and, at ten million, returned `EOF`
for the rest of it — sticky by design, so the grammar winds down. Its comment said "a
valid file finishes well under this bound; it is a safety net, not a size limit"; at
about five lookahead steps per token a legal file of two million tokens reached it,
and what it got was a syntax error in the middle of a file that has none. The largest
compact-model files in circulation are one to two megabytes, so a PDK library that
concatenates a few of them, or a generated model with a large unrolled body, was within
a factor of two of the guard.

## What changed

The condition the guard was written for is a parser that makes no progress, and
consuming a token is progress. `do_bump` — the one place the parser advances —
resets the step counter, and `nth` counts the lookahead steps since then; the limit,
now `PARSER_STALL_LIMIT`, keeps Enhancement-220's ten million. A legal file of any
size parses (the counter never exceeds the few dozen steps the grammar spends on one
token), and a parser spinning in error recovery on one token still winds down to
`EOF` after ten million steps and reports what it collected, exactly as before.

## Verification

`vafcrash2_examples` (Enhancement-220's suite) gains three checks: a module of
340 000 statements (4.4 MB, 2.4 million tokens, past the old boundary of 333 301)
compiles, in 1.6 s; its output holds no "unexpected token EOF"; and Enhancement-220's
keyword-salad recovery stress still ends with a clean error. The first two fail on the
E-709 binaries. By hand: the table above.

## What this does not do

- Nothing bounds a file's size now: a 10 MB module compiles, in 144 s and 5.6 GB —
  the cost of a 400 000-statement analog block, not of the parser. A size the
  compiler will not handle is a memory question, not a grammar one.
- The guard still returns `EOF` rather than a message of its own when it fires; that
  case is a malformed file whose errors have already been reported, and the
  Enhancement-220 behaviour is kept.
