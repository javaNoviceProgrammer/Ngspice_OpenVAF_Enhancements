# Enhancement-352 — general N-variable Volterra formulation for OSDI `.disto`

Derived from ngspice's own `dloadfns.c` primitives and `diodisto.c` usage, and
verified to reproduce the built-in diode's HD2/HD3 to 4e-9. This is the spec the
generic `osdidisto.c` implements. It is written down because a distortion result
that is off by a constant factor looks entirely plausible, so the convention has
to be pinned rather than re-derived from memory.

## Coefficient convention

OpenVAF emits **raw partial derivatives** for `col1 <= col2 (<= col3)`:

    f_jk  = d2 I / dv_j dv_k          (taylor2 entries)
    f_jkl = d3 I / dv_j dv_k dv_l     (taylor3 entries)

The simulator converts them to the Taylor coefficients the formulas below use,
folding in `1/n!` and the multinomial multiplicity for repeated indices:

    c2_jj  = (1/2) f_jj                  c2_jk  = f_jk            (j<k)
    c3_jjj = (1/6) f_jjj                 c3_jjk = (1/2) f_jjk     (two equal)
                                         c3_jkl = f_jkl           (all distinct)

Sanity check against `diodset.c`, which is the reference: for the forward diode
`gd = csat*e/vte`, it stores `g2 = 0.5*gd/vte` = (1/2) d2I/dV2 and
`g3 = g2/(3*vte)` = (1/6) d3I/dV3. Matches `c2_jj` / `c3_jjj` exactly.

## Kernels

For model input `i` (a branch voltage with node pair from `descriptor.inputs`),
the kernel at a given harmonic slot is the node difference read out of the job
vectors, exactly as `diodisto.c` does:

    H_i = solution[node_1(i)] - solution[node_2(i)]

with these slots: `r1H1/i1H1` (f1), `r1H2/i1H2` (f2), `r2H11/i2H11` (2f1),
`r2H1m2/i2H1m2` (f1-f2). For the "minus f2" modes the f2 kernel is CONJUGATED
(`i1hm2x = -i1h2x` in the reference).

All products below are complex; the real part is stamped into `CKTrhs` and the
imaginary part into `CKTirhs`.

## The modes

Writing `S2 = sum over stored j<=k`, `S3 = sum over stored j<=k<=l`:

    D_TWOF1   (2f1)     I = S2 c2_jk * H1_j H1_k

    D_THRF1   (3f1)     I = S2 c2_jk * (H1_j K11_k + H1_k K11_j)
                          + S3 c3_jkl * H1_j H1_k H1_l

    D_F1PF2   (f1+f2)   I = S2 c2_jk * (H1_j H2_k + H1_k H2_j)

    D_F1MF2   (f1-f2)   as F1PF2 with H2 -> conj(H2)

    D_2F1MF2  (2f1-f2)  I = (1/3) * {
                              S2 c2_jk * [ 2(H1_j K1m2_k + H1_k K1m2_j)
                                           + H2_j K11_k + H2_k K11_j ]
                            + S3 c3_jkl * [ H1_j H1_k H2_l
                                          + H1_j H1_l H2_k
                                          + H1_l H1_k H2_j ] }

The 1/3 is not a normalisation choice -- it is in `D1n2F12`, commented there as
"divided by 3 to get kernel (otherwise we get 3*kernel)".

## Reduction check at N = 1

Every mode must collapse to the hard-coded 1-variable helper, which is how the
generalisation is validated before any circuit is run:

    D_TWOF1   c2 H1^2                          == D1n2F1(g2,H1)
    D_THRF1   2 c2 H1 K11 + c3 H1^3            == D1n3F1(g2,g3,H1,K11)
    D_F1PF2   2 c2 H1(f1) H1(f2)               == D1nF12(g2,...)
    D_2F1MF2  (1/3)[4 c2 H1 K1m2 + 2 c2 H2 K11
                    + 3 c3 H1^2 H2]            == D1n2F12(g2,g3,...)

## Reactive part

The resistive and reactive tensors are separate (`load_taylor2` writes
`[resist, react]` pairs). The reactive contribution enters exactly as in
`diodisto.c`: with the same formula but the charge coefficients, then

    re  +=  -omega * Im(reactive_result)
    im  +=  +omega * Re(reactive_result)

## Stamping

For a tensor entry with residual row `r`, add the resulting complex current at
the row's node with the sign convention `diodisto.c` uses:

    CKTrhs[node]  -= re;    CKTirhs[node]  -= im;

The row->node mapping is the instance's `node_mapping[r]`. Stamping this way
inherits ngspice's analysis-level harmonic normalisation automatically -- which
is why the earlier Python check appeared to differ by exactly 2 (HD2) and 4
(HD3): those factors are applied by the analysis, not by the device.
