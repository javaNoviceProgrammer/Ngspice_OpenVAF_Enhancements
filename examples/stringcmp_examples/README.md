# stringcmp_examples — string relational comparison (Enhancement-106)

String equality (`==`/`!=`) already worked, but the relational operators
(`<`, `<=`, `>`, `>=`) rejected string operands (`typed mismatch`).
Enhancement-106 makes them perform a lexicographic comparison (via `strcmp`),
completing the string comparison surface.

`stringcmp_demo.va` evaluates `"abc" < "abd"` (=1), `"abd" > "abc"` (=1),
`"abc" <= "abc"` (=1), `"abc" >= "abd"` (=0), `"abc" < "abc"` (=0),
`"abc" == "abc"` (=1, equality still works), and uses a string relational as an
`if` condition (`"high" < "low"` → true). Run: `python3 verify_stringcmp.py`
(8 checks).
