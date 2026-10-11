# unaryparam_examples — Enhancement-857

[E-857](../../enhancements_doc/Enhancement-857.md): F2 of the
[third robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

numparam read a minus after a binary operator by setting a flag that only a number consumed:
- **Before a name, a parenthesis or a function** the formula was refused and the netlist not
  loaded: `{2*-p}`, `{1/-(2)}`, `{2*-sin(1)}`.
- **A second minus** lost a sign without a word: `{2*--2}` was −4, `{2---2}` 4.
- **Before a power** the number was negated before `^` saw it: `{2*-3^2}` was 18, where the
  B-source and `let` give −18.
- **A plus** there was a misplaced operator.

A sign after an operator now takes the power chain after it as its operand, as the B-source's
grammar and `let`'s do. `let` takes a unary plus.

The checks:
- **[1]** Before a name: `{2*-p}`, `{2 * - p}`.
- **[2]** Before a parenthesis and a function.
- **[3]** Two or three signs.
- **[4]** A sign before a power takes the chain.
- **[5]** A unary plus after an operator.
- **[6]** A sign with nothing after it is refused, naming it.
- **[7]** The same through a subcircuit parameter and an element value.
- **[8]** `let` takes a unary plus.
- **[9]** (control) The forms that already worked.
- **[10]** 34 expressions: the `.param` and the B-source agree on each.

Run: `python3 verify_unaryparam.py` (10 checks per solver). On the E-855 binaries all but the
control [9] fail.
