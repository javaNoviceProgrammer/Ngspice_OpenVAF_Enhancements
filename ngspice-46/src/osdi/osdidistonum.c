/* Enhancement-359: numerical distortion tensors for Verilog-A (OSDI) devices.
 *
 * Enhancement-352 obtained the 2nd/3rd-order Taylor tensors `.disto` needs by
 * having the compiler emit a symbolic closed form for them. That is an enormous
 * amount of work to evaluate ONCE per instance per analysis: on ASMHEMT it cost
 * 707k intermediate derivatives, 1.4M MIR instructions, a 30MB .osdi and a
 * 20-49x compile-time regression, and it forced an ABI bump that made existing
 * models unusable without recompiling.
 *
 * The model already publishes its FIRST derivatives analytically -- that is the
 * Jacobian every analysis loads. The higher derivatives follow by differencing
 * THAT at the operating point:
 *
 *     d2 R_r/dv_p dv_q  =  d/dv_q [ J_rp ]
 *     d3 R_r/dv_p dv_q dv_s = d2/dv_q dv_s [ J_rp ]
 *
 * Differencing an already-analytic first derivative (rather than the residual)
 * keeps the accuracy high: central differences give O(h^2), and measured against
 * exact closed forms this lands at ~1e-11 for 2nd order and ~1e-8 for 3rd --
 * comfortably below the 1.9e-6 floor at which the built-in-diode oracle already
 * sits, that floor being a $vt constant difference.
 *
 * The tensors are evaluated at the DC operating point, so they do NOT depend on
 * frequency: this runs once per instance at D_SETUP and every frequency point
 * then reuses it.
 *
 * The entries are emitted in exactly the (row, col...) form the analytic path
 * produced, so the whole Volterra contraction in osdidisto.c is unchanged. The
 * one difference is the coordinate system: NODE indices rather than "model
 * inputs". That is a simplification, not a compromise -- it removes the hi/lo
 * pair bookkeeping, and with it E-352's blind spot for a nonlinearity in a
 * ground-referenced probe (which has no pair and so was silently dropped).
 *
 * TWO THINGS THIS MUST GET RIGHT, both of which produced plausible-but-wrong
 * numbers while prototyping rather than any visible failure:
 *
 *  - COLLAPSED NODES. `V(a,b) <+ 0` shorts nodes together, and several instance
 *    node indices then share ONE solution entry -- MEXTRAM collapses three onto
 *    one. Treating them as independent perturbs the shared node once per alias
 *    and double-counts it in the contraction; that showed up as a ~0.2% error.
 *    Everything here is therefore indexed by DISTINCT GLOBAL node.
 *  - THE RESISTIVE JACOBIAN ARRAY. `write_jacobian_array_resist` writes a dense
 *    array of the RESISTIVE entries only, so its index is a running count of
 *    those, NOT an index into `jacobian_entries[]`. The two coincide only for a
 *    model with no charge storage.
 */

#include "ngspice/ngspice.h"

#include "ngspice/cktdefs.h"
#include "ngspice/devdefs.h"
#include "ngspice/sperror.h"

#include "osdi.h"
#include "osdidefs.h"
#include "osdidistonum.h"

/* Perturbation steps, relative to the local voltage scale with a floor so a
 * node sitting at zero still gets a usable one.
 *
 * The two orders want DIFFERENT steps and a single compromise serves neither.
 * A central difference of the analytic jacobian has truncation O(h^2) and
 * roundoff O(eps/h), so 2nd order wants a small step; the 3rd order's SECOND
 * difference has roundoff O(eps/h^2) and needs a larger one. Measured against
 * exact closed forms on an exponential diode:
 *
 *      h/scale     2nd-order err     3rd-order err
 *      1e-6            2e-10             7e-7
 *      1e-5            9e-9              1e-9      <- 3rd order optimum
 *      1e-4            8e-7              4e-7
 *      1e-3            8e-5              4e-5
 *
 * so 1e-6 for 2nd order and 1e-5 for 3rd. Using one step of 1e-3 for both put
 * the whole result off by ~8e-5, which is the top row of that table. */
static double numdisto_scale(const CKTcircuit *ckt, const uint32_t *gnodes,
                             uint32_t K)
{
    double scale = 0.0;
    uint32_t k;
    for (k = 0; k < K; k++) {
        double v = fabs(ckt->CKTrhsOld[gnodes[k]]);
        if (v > scale)
            scale = v;
    }
    if (scale < 1e-2)
        scale = 1e-2;
    return scale;
}

/* Evaluate the instance with the solution shifted by `shift` (indexed like
 * gnodes) and write the resistive+reactive Jacobian into jr/jx, both laid out
 * as one entry per jacobian_entries[] slot (0 where the flag is absent). */
static void numdisto_jac_at(CKTcircuit *ckt, const OsdiDescriptor *descr,
                            GENinstance *gi, void *inst, void *model,
                            OsdiSimInfo *probe, double *scratch,
                            const uint32_t *gnodes, const double *shift,
                            uint32_t K, double *jr, double *jx,
                            double *bufr, double *bufx)
{
    int n = ckt->CKTmaxEqNum;
    int i;
    uint32_t k, e, ri, xi;
    OsdiNgspiceHandle h = (OsdiNgspiceHandle){.kind = 3, .name = gi->GENname};

    /* CKTrhsOld holds CKTmaxEqNum entries, so the last valid index is n-1 --
     * ngspice's own code copies it as `CKTmaxEqNum * sizeof(double)`. `i <= n`
     * read one element past the end on every .disto run (caught by ASan). */
    for (i = 0; i < n; i++)
        scratch[i] = ckt->CKTrhsOld[i];
    /* assignment, not accumulation: gnodes are distinct by construction, but
     * this also keeps the shift exact if a caller passes a repeated entry */
    for (k = 0; k < K; k++)
        scratch[gnodes[k]] = ckt->CKTrhsOld[gnodes[k]] + shift[k];

    probe->prev_solve = scratch;
    descr->eval(&h, inst, model, probe);

    if (descr->write_jacobian_array_resist)
        descr->write_jacobian_array_resist(inst, model, bufr);
    if (descr->write_jacobian_array_react)
        descr->write_jacobian_array_react(inst, model, bufx);

    ri = xi = 0;
    for (e = 0; e < descr->num_jacobian_entries; e++) {
        uint32_t fl = descr->jacobian_entries[e].flags;
        jr[e] = (fl & JACOBIAN_ENTRY_RESIST) ? bufr[ri++] : 0.0;
        jx[e] = (fl & JACOBIAN_ENTRY_REACT) ? bufx[xi++] : 0.0;
    }
}

void osdi_numdisto_free(OsdiNumDisto *nd)
{
    if (!nd)
        return;
    tfree(nd->t2);
    tfree(nd->t3);
    tfree(nd->gnodes);
    tfree(nd->g_of_node);
    nd->t2 = NULL;
    nd->t3 = NULL;
    nd->gnodes = NULL;
    nd->g_of_node = NULL;
    nd->n2 = nd->n3 = nd->K = 0;
}

int osdi_numdisto_build(CKTcircuit *ckt, const OsdiDescriptor *descr,
                        GENinstance *gi, void *inst, void *model,
                        const uint32_t *node_mapping, OsdiSimInfo *base_info,
                        OsdiNumDisto *nd)
{
    int n = ckt->CKTmaxEqNum;
    uint32_t M = descr->num_nodes;
    uint32_t NE = descr->num_jacobian_entries;
    uint32_t NJR = descr->num_resistive_jacobian_entries;
    uint32_t NJX = descr->num_reactive_jacobian_entries;
    uint32_t p, q, s, e, k;
    int rc = OK;

    memset(nd, 0, sizeof(*nd));
    if (M == 0 || NE == 0 || !descr->eval || !descr->write_jacobian_array_resist)
        return OK;

    /* ---- distinct global nodes (collapse-aware) --------------------------- */
    nd->gnodes = TMALLOC(uint32_t, M);
    nd->g_of_node = TMALLOC(uint32_t, M);
    nd->K = 0;
    for (p = 0; p < M; p++) {
        uint32_t gp = node_mapping[p];
        nd->g_of_node[p] = UINT32_MAX;
        if (gp == 0 || gp >= (uint32_t)n)
            continue;                       /* ground, or out of range: not a variable */
        for (k = 0; k < nd->K; k++)
            if (nd->gnodes[k] == gp)
                break;
        if (k == nd->K)
            nd->gnodes[nd->K++] = gp;
        nd->g_of_node[p] = k;
    }
    if (nd->K == 0) {
        osdi_numdisto_free(nd);
        return OK;
    }

    {
        uint32_t K = nd->K;
        double vscale = numdisto_scale(ckt, nd->gnodes, K);
        double h2 = 1e-6 * vscale;   /* 2nd order */
        /* h3 is chosen AFTER the 2nd-order pass, from the curvature scale it
         * measures -- see below. The operating voltage is the wrong yardstick:
         * a diode's jacobian turns over in v_t = 26mV while a polynomial's
         * varies over volts, so one voltage-relative rule is far too coarse for
         * one of them (it put HD3 11% out on a cubic biased at 0V). */
        double h3 = 0.0;
        double *scratch = TMALLOC(double, (size_t)n + 1);
        double *shift = TMALLOC(double, K);
        double *bufr = TMALLOC(double, NJR ? NJR : 1);
        double *bufx = TMALLOC(double, NJX ? NJX : 1);
        double *jp = TMALLOC(double, NE), *jm = TMALLOC(double, NE);
        double *xp = TMALLOC(double, NE), *xm = TMALLOC(double, NE);
        double *j0 = TMALLOC(double, NE), *x0 = TMALLOC(double, NE);
        double *jpp = TMALLOC(double, NE), *jpm = TMALLOC(double, NE);
        double *jmp = TMALLOC(double, NE), *jmm = TMALLOC(double, NE);
        double *xpp = TMALLOC(double, NE), *xpm = TMALLOC(double, NE);
        double *xmp = TMALLOC(double, NE), *xmm = TMALLOC(double, NE);
        uint32_t cap2 = 64, cap3 = 64;

        OsdiSimInfo probe = *base_info;
        /* Limiting OFF: we want the derivative of the true device function, and a
         * probe step could otherwise land in the clamped region and flatten it. */
        probe.flags = base_info->flags & ~(uint32_t)(ENABLE_LIM | INIT_LIM);

        nd->t2 = TMALLOC(OsdiNumT2, cap2);
        nd->t3 = TMALLOC(OsdiNumT3, cap3);

        for (k = 0; k < K; k++)
            shift[k] = 0.0;
        numdisto_jac_at(ckt, descr, gi, inst, model, &probe, scratch,
                        nd->gnodes, shift, K, j0, x0, bufr, bufx);

        /* ---- second order: one +-h sweep per distinct node ---------------- */
        double curv = 0.0;      /* max |dJ/dv| / |J| seen */
        for (q = 0; q < K; q++) {
            shift[q] = h2;
            numdisto_jac_at(ckt, descr, gi, inst, model, &probe, scratch,
                            nd->gnodes, shift, K, jp, xp, bufr, bufx);
            shift[q] = -h2;
            numdisto_jac_at(ckt, descr, gi, inst, model, &probe, scratch,
                            nd->gnodes, shift, K, jm, xm, bufr, bufx);
            shift[q] = 0.0;

            for (e = 0; e < NE; e++) {
                uint32_t row = descr->jacobian_entries[e].nodes.node_1;
                uint32_t col = descr->jacobian_entries[e].nodes.node_2;
                uint32_t cg;
                double dr, dx;
                if (row >= M || col >= M)
                    continue;
                cg = nd->g_of_node[col];
                if (cg == UINT32_MAX || cg > q)
                    continue;               /* keep col1 <= col2 only */
                dr = (jp[e] - jm[e]) / (2.0 * h2);
                dx = (xp[e] - xm[e]) / (2.0 * h2);
                if (dr == 0.0 && dx == 0.0)
                    continue;
                /* curvature scale: |dJ/dv| / |J| is 1/V0, the reciprocal of the
                 * voltage over which the jacobian turns over (v_t for a diode,
                 * volts for a polynomial). Keep the largest, i.e. the tightest
                 * scale present in the device. */
                if (fabs(j0[e]) > 1e-300) {
                    double c = fabs(dr) / fabs(j0[e]);
                    if (c > curv)
                        curv = c;
                }
                if (nd->n2 == cap2) {
                    cap2 *= 2;
                    nd->t2 = TREALLOC(OsdiNumT2, nd->t2, cap2);
                }
                nd->t2[nd->n2].row = row;
                nd->t2[nd->n2].c1 = cg;
                nd->t2[nd->n2].c2 = q;
                nd->t2[nd->n2].resist = dr;
                nd->t2[nd->n2].react = dx;
                nd->n2++;
            }
        }

        /* Optimal step for a SECOND difference balances truncation O(h^2) against
         * roundoff O(eps/h^2), giving h ~ V0 * eps^(1/4) with V0 = 1/curv the
         * curvature scale measured above. Bounded either side so a perfectly
         * linear device (curv == 0) and a pathological one both stay sane. */
        h3 = (curv > 0.0) ? 1.2e-4 / curv : 1e-3;
        if (h3 < 1e-6)  h3 = 1e-6;
        if (h3 > 1e-1)  h3 = 1e-1;

        /* ---- third order: mixed second difference over node pairs --------- */
        for (q = 0; q < K; q++) {
            for (s = q; s < K; s++) {
                double denom;
                if (q == s) {
                    /* d2 J/dv_q^2 from the three points already needed */
                    shift[q] = h3;
                    numdisto_jac_at(ckt, descr, gi, inst, model, &probe, scratch,
                                    nd->gnodes, shift, K, jpp, xpp, bufr, bufx);
                    shift[q] = -h3;
                    numdisto_jac_at(ckt, descr, gi, inst, model, &probe, scratch,
                                    nd->gnodes, shift, K, jmm, xmm, bufr, bufx);
                    shift[q] = 0.0;
                    denom = h3 * h3;
                    for (e = 0; e < NE; e++) {
                        jpm[e] = j0[e];
                        xpm[e] = x0[e];
                    }
                } else {
                    shift[q] = h3;  shift[s] = h3;
                    numdisto_jac_at(ckt, descr, gi, inst, model, &probe, scratch,
                                    nd->gnodes, shift, K, jpp, xpp, bufr, bufx);
                    shift[q] = h3;  shift[s] = -h3;
                    numdisto_jac_at(ckt, descr, gi, inst, model, &probe, scratch,
                                    nd->gnodes, shift, K, jpm, xpm, bufr, bufx);
                    shift[q] = -h3; shift[s] = h3;
                    numdisto_jac_at(ckt, descr, gi, inst, model, &probe, scratch,
                                    nd->gnodes, shift, K, jmp, xmp, bufr, bufx);
                    shift[q] = -h3; shift[s] = -h3;
                    numdisto_jac_at(ckt, descr, gi, inst, model, &probe, scratch,
                                    nd->gnodes, shift, K, jmm, xmm, bufr, bufx);
                    shift[q] = 0.0; shift[s] = 0.0;
                    denom = 4.0 * h3 * h3;
                }

                for (e = 0; e < NE; e++) {
                    uint32_t row = descr->jacobian_entries[e].nodes.node_1;
                    uint32_t col = descr->jacobian_entries[e].nodes.node_2;
                    uint32_t cg;
                    double dr, dx;
                    if (row >= M || col >= M)
                        continue;
                    cg = nd->g_of_node[col];
                    if (cg == UINT32_MAX || cg > q)
                        continue;           /* keep col1 <= col2 <= col3 */
                    if (q == s)
                        dr = (jpp[e] - 2.0 * jpm[e] + jmm[e]) / denom,
                        dx = (xpp[e] - 2.0 * xpm[e] + xmm[e]) / denom;
                    else
                        dr = (jpp[e] - jpm[e] - jmp[e] + jmm[e]) / denom,
                        dx = (xpp[e] - xpm[e] - xmp[e] + xmm[e]) / denom;
                    if (dr == 0.0 && dx == 0.0)
                        continue;
                    if (nd->n3 == cap3) {
                        cap3 *= 2;
                        nd->t3 = TREALLOC(OsdiNumT3, nd->t3, cap3);
                    }
                    nd->t3[nd->n3].row = row;
                    nd->t3[nd->n3].c1 = cg;
                    nd->t3[nd->n3].c2 = q;
                    nd->t3[nd->n3].c3 = s;
                    nd->t3[nd->n3].resist = dr;
                    nd->t3[nd->n3].react = dx;
                    nd->n3++;
                }
            }
        }

        /* restore the device to its converged state so nothing downstream sees
         * a probe evaluation */
        for (k = 0; k < K; k++)
            shift[k] = 0.0;
        numdisto_jac_at(ckt, descr, gi, inst, model, base_info, scratch,
                        nd->gnodes, shift, K, j0, x0, bufr, bufx);

        tfree(scratch); tfree(shift); tfree(bufr); tfree(bufx);
        tfree(jp); tfree(jm); tfree(xp); tfree(xm); tfree(j0); tfree(x0);
        tfree(jpp); tfree(jpm); tfree(jmp); tfree(jmm);
        tfree(xpp); tfree(xpm); tfree(xmp); tfree(xmm);
    }
    return rc;
}
