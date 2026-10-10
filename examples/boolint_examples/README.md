# boolint_examples — Enhancement 845

[E-845](../../enhancements_doc/Enhancement-845.md), F1 of the
[second robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

openvaf-r types a comparison, `&&`, `||`, `!` and `$param_given` as Bool. The LRM's value is the
integer 1 or 0, and wherever one met an integer, the integer was cast to Bool instead:
- `(n > 0) ? n : (n < 0)` was 1 for n = 5, and `n == (n > 0)` was true. The ternary and the
  equality resolved to their Bool overload.
- `case (n > 0) 5:` matched.
- An untyped parameter with such a default, `parameter pb = (n > 0);`, was typed Bool, which a
  parameter cannot be. The compiler panicked (exit 101), even when it was never read.

`boolint.va` holds the expressions and `boolparam.va` the untyped parameters, so a panic in one
does not hide the other:
- **[1]** The ternary, with the logical branch on either side, and controls: a real branch and
  two logical ones.
- **[2]** `==` and `!=` against a logical result, `$param_given(n) == 2` among them.
- **[3]** `case (n > 0)` with the item 5, and the controls `case (n > 0) 1:` and `case (1)`.
- **[4]** The ternary into an integer variable.
- **[5]** The same at run time, from a node voltage.
- **[6]** Untyped parameters with a comparison, `&&`, `!`, `$param_given`, a localparam, an array
  and the ternary as their default. Each is an integer, so `pb/2` is 0, and `pb=7` on the card is
  taken.

Run: `python3 verify_boolint.py` (30 checks per solver). On the E-844 compiler 11 fail, and
`boolparam.va` panics, so its 10 cannot run.
