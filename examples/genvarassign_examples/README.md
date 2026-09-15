# genvarassign_examples — Enhancement-638

An assignment to a genvar inside its own loop (`for (i=0;i<3;i=i+1) begin
i = i + 1; … end`) is refused before the loop is unrolled, with the statement
quoted and the rule stated (a genvar takes its values from the loop header
only); a nested loop that reuses the genvar as its own loop variable is
refused as reuse. It used to be substituted like any other use of `i`, and the
parser reported `unexpected token integer` at `0 = 0 + 1` in a generated copy,
once per copy. Legal loops — comparisons on the genvar, `k = i`, `a[i] = i`,
nested loops over different genvars — are pinned to still compile and compute.

Run: `python3 verify_genvarassign.py` (4 checks per solver, both solvers).
