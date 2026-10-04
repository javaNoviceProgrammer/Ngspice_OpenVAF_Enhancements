# Enhancement-791: a diagnostic on a long line quotes a window around what it points at — the depth error on a generated 100 000-term sum was 664 KB

**Scope:** D1 of the
[openvaf-r hunt of 2026-10-04](../docs/bug_hunts/2026-10-04_openvaf-r-run-time-domains-filters-and-instances.md).
openvaf: `basedb/src/diagnostics/sink.rs` (`ConsoleSink::clip_long_lines`, `ClippedFile`,
`ClippedSrc`; `MAX_QUOTED_LINE` 240, `QUOTED_CONTEXT` 60); `test_data/syn_ui/long_line.va` (a
snapshot). `examples/vafslips_examples/` (section [1], seven checks). **openvaf only.**

**Suites:** [`vafslips_examples`](../examples/vafslips_examples/) 67 of 67 per solver (4 of the 7
in [1] fail on the E-790 binaries); `hunt17diag` (its depth-error check); the `basedb` `syn_ui`
snapshots; the workspace tests; every bundled Verilog-A file compiled with the old and the new
binary (below); the full sweep, 537 of 537.

## What was wrong

codespan-reporting quotes every source line a label touches, whole. A generated one-line
expression is the case where that hurts. E-718's depth bound reports at the 32 769th operator of
a chain, and a 100 000-term sum on one line drew a 664 KB diagnostic: the 500 KB line, then
164 KB of spaces to place one caret under column 163 846. Any error on a long line did the same,
at any position. An undefined name at the end of a 3 000-term line was 42 KB.

## The change

`ConsoleSink::add_report` looks at the files a report's labels point into. A file with a line
longer than 240 bytes is quoted from a clipped copy, and the labels are moved into the copy:

- each such line keeps 60 bytes on either side of every label's start and end;
- windows closer than the marker are merged, and the cuts are marked `...`;
- a long line with no label on it (a context line between the two ends of a multi-line label)
  keeps its first 120 bytes;
- the cuts fall on character boundaries.

Line breaks are kept, so line numbers are unchanged. `location()` maps back to the original, so
the position above the snippet is the line's real column. Whether a file has a long line is
worked out once per file. Lines of 240 bytes or less are quoted as before.

```
error: 'nosuch' was not found in the current scope
  --> longend.va:3:21018
  |
3 | ...,n)+V(p,n)+V(p,n)+V(p,n)+V(p,n)+V(p,n)+V(p,n)+V(p,n)+V(p,n)+nosuch;
  |                                                                ^^^^^^ not found
```

| input | old | new |
|---|---|---|
| depth error, 100 000 terms on one line | 664 578 bytes | 923 bytes |
| undefined name after 3 000 terms | 42 287 bytes | 379 bytes |
| a name redeclared 3 000 bytes after its first declaration | the line, twice underlined | both windows, `...` between |

## The checks

vafslips [1]:

- the undefined name at the end of the 21 000-byte line: one error, under 2 KB;
- the real column;
- the window ends at the name and starts with `...`, and the caret is under the name;
- two labels 3 000 bytes apart on one line: one window each;
- a 230-byte line is quoted whole;
- a comment of two-byte characters is cut on a character boundary.

The `syn_ui` snapshot `long_line.va` pins the rendering of a parse error at column 1219.

Compiled with the old and the new binary (`--dry-run`), the 1 026 bundled Verilog-A files report
the same diagnostics. Two print less: `vafbitsetdomain`'s 66 L011 warnings (200 KB to 52 KB) and
`vafcrash3`'s `crash_strlit.va` (52 KB to 21 KB).

## Limits

- The 100 000-term line still takes 14 s to *reject*. A 32 000-term line takes 13 s to compile,
  with no diagnostic at all. The time is spent in rowan, the syntax-tree library. Its node cache
  deduplicates nodes of up to three children. When its table grows, it rehashes every cached
  node by walking the node's whole subtree (`node_cache::node_hash` recurses), so a left-leaning
  chain costs O(n²): 8 000 terms 0.86 s, 16 000 3.3 s, 32 000 13.2 s. The same chain written
  with spaces or line breaks has four or more children per node. It is never cached and compiles
  in 0.2 s. The fix lives in rowan (storing each node's hash beside it), and would mean carrying
  a patched copy of the crate in the workspace. Not done here.
