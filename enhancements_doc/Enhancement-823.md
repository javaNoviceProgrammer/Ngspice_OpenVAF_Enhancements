# Enhancement-823: `pre_osdi` in an included library names its files beside the library, not beside the top deck

**Scope:** F7 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).

ngspice:
- `frontend/inpcom.c`:
  - `inp_osdi_paths_at` rewrites the relative names of a `pre_osdi` or `osdi` line in an
    included file.
  - The reader calls it for those lines when `call_depth > 0`.
  - `inp_top_dir` remembers the deck's own directory.

`examples/libsens_examples/` (new; section [1], eight checks). **ngspice only.**

**Suites:** [`libsens_examples`](../examples/libsens_examples/) 18 of 18 per solver (6 of the 8
checks in [1] fail on the E-822 binaries; the other two are controls: the deck's own
`pre_osdi`, and a name found nowhere). The full sweep, 544 of 544.

## What was wrong

```spice
* sub/inc.lib, beside sub/gres.osdi and sub/gres.va
.control
pre_osdi gres.osdi          ; or: pre_osdi -va gres.va
.endc
.model gm gres g=2m
```

`.include sub/inc.lib` from `top.cir` failed, from any working directory:
- `pre_osdi gres.osdi`: `Error opening osdi lib "gres.osdi"`;
- `pre_osdi -va gres.va`: `pre_osdi: no such Verilog-A source: ./gres.va`.

The `pre_` commands run before the circuit is read, with `inputdir` set to the top deck's
directory. They resolve a relative name against it (Enhancement-500 made `-va` agree).
Nothing remembered which file a control line came from. A nested `.include` resolves against
the file that includes it, but a `pre_osdi` in that file did not. A model library that ships
`models.lib` and `models.osdi` side by side could not load its object by a relative name.

## The change

While the reader reads an included file (a `.include` at any depth, or a `.lib` section), it
looks at each `pre_osdi` or `osdi` line in a `.control` block. An argument is rewritten when it
is relative and names a regular file in that file's directory:
- **`pre_osdi`, a file beneath the deck's own directory:** the name relative to the deck. The
  pre-pass resolves against that directory, so `pre_osdi -va` gives the object the same name as
  the same line written in the deck: `osdi/sub_gres.osdi`, after Enhancement-573's rule.
- **Every other case:** the file's absolute path. This includes the plain `osdi` command, which
  runs after the pre-pass, when no deck directory is set.

Some arguments are left as written, so the commands' own search and messages apply to them:
- flags;
- absolute names;
- names not found beside the file.

A path with a space is quoted. The object `-va` compiles still goes to `osdi/` beside the top
deck, which can be written to when a library sits in a read-only tree.

## The checks

`libsens_examples` [1], each run from a directory that is neither the deck's nor the library's:
- `.include sub/inc.lib` holding `pre_osdi gres.osdi`: i(v1) = −2 mA (was "Error opening osdi
  lib").
- The same in a `.lib` section (−4 mA), two includes deep (−5 mA), and under a path with a
  space (−6 mA).
- `pre_osdi -va gres.va`: compiled from `sub/gres.va` into `osdi/sub_gres.osdi` beside the top
  deck, −3 mA (was "no such Verilog-A source").
- The plain `osdi gres.osdi`: the device is loaded.
- The deck's own relative `pre_osdi` (control): −1 mA.
- A name not found beside the library is left as written: the error names `nothere.osdi`.

## Limits

- Other commands that take a file name in an included `.control` block (`pre_snp`, `source`,
  `load`) still resolve against the top deck or the working directory.
