# Enhancement-619: `writemc` columns in blue, and the workbook's fonts as options

**Scope:** `src/frontend/mcsave.c` — the xlsx writer builds `styles.xml` from four fonts
(every cell's, and the header row's three styles for a model, an instance and a
`writemc` column) instead of a fixed string; five options read at each write:
`savemc_font`, `savemc_fontsize`, `savemc_model`, `savemc_instance`, `savemc_writemc`
(`mcs_fonts()`, `mcs_font_parse()`, `xlsx_font_xml()`); `src/frontend/inpcom.c` — the
font name keeps its case (Enhancement-612's table); `src/frontend/spiceif.c` — the five
names are known options. `examples/savemc_examples/` grows 34 → 36 checks per solver
(`writemc_examples`' xlsx parser widened); handbook
[§3.6](../docs/handbook/03-ngspice-workflows.md), the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §8, the
suite README. **ngspice only.**

**Suites:** [`savemc_examples`](../examples/savemc_examples/) 36 of 36 per solver, both
solvers; `writemc`, `osdimc` green; full sweep 505 of 505.

## What was asked

Enhancement-617 set a model parameter's name in bold in the workbook's header row and
left an instance parameter's regular. Two more things were asked for: a column that is
neither — a value computed after the run and put on the row by `writemc` or
`montecarlo -writemc` — should stand out in **blue**; and the fonts should be
adjustable from the deck.

## What changed

**The default header.** Three kinds of column, three styles: a model card's parameter
(`rm:r`, `@rm[r]`) bold; an instance's, a subcircuit call's, a `.param` (`r1`, `n1:dr`,
`x1.c`, `@n1[dr]`) regular; a `writemc` / `-writemc` column (`ia`, `pk`) blue. The three
fixed columns are in the base font. Data cells are all in the base font.

**Five options**, read at every write of the workbook so a `set` in the `.control`
block takes effect too:

| option | default | what it sets |
|---|---|---|
| `savemc_font=<name>` | `Calibri` | the font of every cell; the name keeps its case, and a name with spaces is quoted: `savemc_font="Times New Roman"` |
| `savemc_fontsize=<pt>` | `11` | its size |
| `savemc_model=<style>` | `bold` | the header style of a model column |
| `savemc_instance=<style>` | `regular` | … of an instance column |
| `savemc_writemc=<style>` | `blue` | … of a `writemc` column |

A `<style>` is a list of `bold`, `italic`, `underline`, `regular` (clears the three and
the colour), a colour name — `black blue red green orange gray purple teal navy brown
magenta cyan yellow white` — or a hex `RRGGBB`, joined with `+`: `savemc_model=bold+navy`,
`savemc_writemc=red+underline`. (`/`, `:` and `|` join as well; a comma does not — the
`.option` card's lexer splits a value there, and `bold,navy` would reach the run as
`bold` and an unknown option `navy`.) The style starts from the kind's default, so
`savemc_model=navy` is bold *and* navy; the last colour named wins. A token that is none
of these is said once and ignored:

```
Warning: .option savemc_writemc: 'shiny' is not a style -- bold, italic, underline, regular, a colour name or RRGGBB, joined with +; ignored
```

```spice
.option savemc=draws.xlsx osdimc savemc_font="Times New Roman" savemc_fontsize=12
.option savemc_model=bold+navy savemc_instance=italic savemc_writemc=red+underline
```

Read back with openpyxl: `rm:r` bold navy, `r1` italic, `ia` red underlined, everything
Times New Roman 12; with no options set, the E-617 workbook plus blue `writemc` headers.
csv and txt are unchanged.

## Verification

| check | result |
|---|---|
| a `writemc ia=` column and a `montecarlo -writemc pk=` column, no options | both blue in the header; model bold, instance and the fixed three regular; Calibri 11 throughout |
| `savemc_font="Times New Roman" savemc_fontsize=12 savemc_model=bold+navy savemc_instance=italic savemc_writemc=red+underline+shiny+1A2B3C` | the styles land, the last colour wins (`1A2B3C`), `shiny` said once, no "unknown option" warning for the five names |
| the E-617 check (`Bold.xlsx`), re-read through the styles table | unchanged |
| `writemc_examples` [6] (its parser widened for a styled header cell), the other 33 checks | unchanged |
| `savemc_examples` | 36 / 36, both solvers |
| full sweep | 505 of 505 |
