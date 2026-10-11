# pzdeflate_examples — Enhancement-856

[E-856](../../enhancements_doc/Enhancement-856.md): F1 of the
[third robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

The pole-zero search finds the roots of det(G + sC) one at a time, dividing each out of the
function it searches next. A root's factor was |p − s|² whenever p − s was complex. That is
right for a pair at a real trial, and not analytic at a complex one. Muller wandered to the
iteration limit around a pair it had started next to, and the plot held the roots found so far:
4 of the campaign's 252 networks lost poles or zeros.

A pair on the jω axis was also never declared: the test of a repeated point asked for equal
imaginary parts and a real part within 1e-12 of |Re s| = 0.

The factor is now (p − s), or (p − s)(p̄ − s) for a pair, and a complex point that repeats to
1e-12 of |s| is where Muller has converged. Beyond the last root, where s·C swamps G, the
search could now converge on rounding noise, so a point there counts as a root only if the
function grows around it as at a zero.

The networks come from the campaign's generator, with their exact roots, the generalized
eigenvalues of the MNA pencil and its Rosenbrock pencil.

The checks:
- **[1]** Two cancelling pairs: the 4 poles and 4 zeros.
- **[2]** A complex pair of zeros among 5.
- **[3]** A pair of zeros on the jω axis and a far real one.
- **[4]** A jω pair that converged and was never declared.
- **[5]** Two more networks, poles and zeros.
- **[6]** None of these warns that the search gave up.
- **[7]** The rational function of [1]'s roots is ngspice's own ac response, to 1e-9.
- **[8]** (control) Past the last root, no roots from the noise at |s| ~ 1e21.
- **[9]** (control) A zero at s ≈ 0 is still a zero.

Run: `python3 verify_pzdeflate.py` (9 checks per solver). On the E-855 binaries 6 fail under
Sparse ([1]–[3], [5]–[7]) and 7 under KLU ([4] too).
