# composevalues_examples — Enhancement-900

`compose name values …`: F6 of the
[analyses correctness campaign of 2026-10-16](../../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md).
The values were parsed as one expression list, so `1 -2 3` made [−1, 3]: a negative value was
subtracted from the one before it, without a word. A word that starts with a sign, follows a
complete value, and sits outside parentheses and brackets now starts a new value, as in a MATLAB
row. See [E-900](../../enhancements_doc/Enhancement-900.md).

- **[1]** `1 -2 3` is [1, −2, 3].
- **[2]** `1, -2, 3` and `1,-2,3` likewise.
- **[3]** `1 +2 3` is [1, 2, 3].
- **[4]** Signed expressions start new values: `1 -2*3 4`, `x -x`, `sin(0) -cos(0)`,
  `1 -(2+3) 4`, `3 -2 +1`, `-1 -2 -3`, `1e-3 -1e-3`.
- **[5]** Eleven random values in [−5, 5], written with `%g`: the same eleven values.
- **[6]** The binary forms are unchanged: `1 - 2 3`, `1-2 3`, `(1 -2) 3`, `2 * -3 4`,
  `2 ^ -1 4`, `x gt -1 7`.
- **[7]** `1 (-2) 3` and the complex `(1, -2) (3,4)` are unchanged.
- **[8]** `1 -`, `1 -foo` and an empty list are still reported, and make no vector.

Run: `python3 verify_composevalues.py` (8 checks per solver). On the E-899 binaries [1] to [5]
fail.
