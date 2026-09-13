# Enhancement-629: `pre_osdi "a path with spaces"` loads — the loaders unquote their file names

**Scope:** `src/frontend/com_dl.c` — `com_osdi` (`pre_osdi` / `osdi`, `-f` and `-va`
included) and `com_codemodel` unquote each file name with `cp_unquote` before opening
it. `examples/osdireload_examples/` grows 6 → 10 checks. **ngspice only.** F12 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`osdireload_examples`](../examples/osdireload_examples/) 10 of 10;
`vacompile`, `lifecycle`, `multimod` green; full sweep 506 of 506.

## What was wrong

| spelling | result |
|---|---|
| `pre_osdi "dir with space/va res.osdi"` | `Error opening osdi lib ""dir with space/va res.osdi""` |
| `pre_osdi -f "/abs/dir with space/va res.osdi"` | the same |
| `pre_osdi dir\ with\ space/va\ res.osdi` | loads `dir`, then `with`, then `space/va` … |
| `pre_osdi 'dir with space/va res.osdi'` | loads |

A path with spaces has to be quoted, and the double-quoted spelling — the one a schematic
tool or a Windows user writes — is the one the command lexer keeps as a single word
*with its quotes on*; single quotes it strips. `com_osdi` handed the word to the loader
as it came, so the file `"dir with space/va res.osdi"`, quotes included, did not exist.
Every KiCad project under a directory with a space (`~/My Projects/…`) met this at its
`pre_osdi` line. `codemodel` read its argument the same way. (The backslash spelling is
the lexer's word splitting, before any command sees the words — quotes are the way to
write such a path, and either kind now works.)

## What changed

- **`pre_osdi` / `osdi` unquote every file name** — `cp_unquote`, as the other
  file-taking commands do — before the `-f` reload, the `-va` compile (whose command line
  E-500 already quoted) or the plain load sees it.
- **`codemodel` does the same.**

```
pre_osdi "dir with space/va res.osdi"          -> i(v1) = -1.00000e-03
pre_osdi -f "/abs/dir with space/va res.osdi"  -> reloads
pre_osdi -va "dir with space/va res.va"        -> compiles, loads
codemodel "dir with space/x dev.cm"            -> loads
```

## Verification

| check | result |
|---|---|
| `osdi "dir with space/va res.osdi"` (relative, double quotes) | loads, −1 mA |
| single quotes | still load |
| an absolute double-quoted path, recompiled in place, `-f` on the same quoted path | reloads, −0.5 mA |
| `-va "dir with space/va res.va"` | compiles and loads, −0.5 mA |
| `codemodel "dir with space/x dev.cm"` | loads (by hand; the version12 binary shows the old doubled-quote error) |
| the six existing checks | unchanged |
| `osdireload_examples` | 10 / 10 |
| full sweep | 506 of 506 |
