/* Enhancement-352: distortion (Volterra) analysis for OSDI / Verilog-A devices.
 *
 * ngspice's `.disto` is a Volterra-series analysis: it needs each device's
 * Taylor expansion of I(v) to THIRD order, not just the operating-point
 * linearisation the Jacobian provides. Built-in devices hand-code those
 * coefficients (`diodset.c` computes `id_x2`, `id_x3`, ...), which is why only
 * four of ~58 of them implement DEVdisto at all.
 *
 * OSDI 0.8 (Enhancement-352) makes the coefficients available for any
 * Verilog-A model: OpenVAF's autodiff is arbitrary-order, so the compiler emits
 * `taylor2_entries`/`taylor3_entries` plus `load_taylor2`/`load_taylor3`.
 * This file is the generic consumer -- written ONCE, it gives every OSDI model
 * distortion analysis.
 *
 * WHY THERE IS NO 3-VARIABLE CEILING HERE
 * ---------------------------------------
 * ngspice's own framework caps out at three controlling variables: `Dderivs`
 * holds derivatives "w.r.t 3 variables" and the DF* helpers take up to 27
 * scalar arguments with no fourth-variable form. That cap is a property of the
 * hard-coded helpers, not of the mathematics. The Volterra contraction is just
 * a symmetric tensor contraction, so this file performs it directly over
 * however many model inputs the device has, and never calls the D1x/DFx
 * helpers. The formulas below are the N-variable generalisation of exactly
 * those helpers (D1x, DFx) -- see DISTO_VOLTERRA_FORMULATION.md, which records each mode
 * together with its N=1 reduction back to the hard-coded form it must match.
 *
 * CONVENTION
 * ----------
 * OpenVAF emits RAW partial derivatives; the 1/n! and the multinomial
 * multiplicity are applied here (`taylor_c2`/`taylor_c3` below). That keeps the
 * ABI free of a convention a reader would have to infer, and it is checked
 * against `diodset.c`, which stores `g2 = 0.5*gd/vte` = (1/2)d2I/dV2 and
 * `g3 = g2/(3*vte)` = (1/6)d3I/dV3.
 */

#include "ngspice/ngspice.h"

#include "ngspice/cktdefs.h"
#include "ngspice/devdefs.h"
#include "ngspice/distodef.h"
#include "ngspice/sperror.h"

#include "osdi.h"
#include "osdidefs.h"

/* ------------------------------------------------------------------ complex */
typedef struct { double re, im; } dcomplex;

static inline dcomplex cx(double re, double im)
{
    dcomplex z; z.re = re; z.im = im; return z;
}
static inline dcomplex cadd(dcomplex a, dcomplex b)
{
    return cx(a.re + b.re, a.im + b.im);
}
static inline dcomplex cmul(dcomplex a, dcomplex b)
{
    return cx(a.re * b.re - a.im * b.im, a.re * b.im + a.im * b.re);
}
static inline dcomplex cscale(dcomplex a, double s)
{
    return cx(a.re * s, a.im * s);
}
static inline dcomplex cconj(dcomplex a)
{
    return cx(a.re, -a.im);
}

/* scratch for load_taylor2/3, grown as needed (mirrors osdinoise.c's approach) */
static double *t2_buf = NULL;
static double *t3_buf = NULL;
static uint32_t t2_len = 0, t3_len = 0;

/* --------------------------------------------------------------- kernels */
/* The kernel of model input `i` at a given harmonic slot: the node difference
 * of that slot's solution vector across the input's node pair. Mirrors what
 * `diodisto.c` does by hand for the diode's single branch voltage. */
static dcomplex input_kernel(const OsdiDescriptor *descr, const uint32_t *node_mapping,
                             uint32_t i, const double *re, const double *im)
{
    uint32_t n1 = descr->inputs[i].node_1;
    uint32_t n2 = descr->inputs[i].node_2;
    uint32_t m1 = (n1 == UINT32_MAX) ? 0 : node_mapping[n1];
    uint32_t m2 = (n2 == UINT32_MAX) ? 0 : node_mapping[n2];
    double r = re[m1] - re[m2];
    double x = im[m1] - im[m2];
    return cx(r, x);
}

/* Taylor coefficient from the RAW partial derivative, folding in 1/n! and the
 * multinomial multiplicity for repeated indices (see the header comment). */
static inline double taylor_c2(double raw, uint32_t a, uint32_t b)
{
    return (a == b) ? 0.5 * raw : raw;
}
static inline double taylor_c3(double raw, uint32_t a, uint32_t b, uint32_t c)
{
    if (a == b && b == c)
        return raw / 6.0;              /* 1/3!            */
    if (a == b || b == c || a == c)
        return 0.5 * raw;              /* multiplicity 3 / 3! */
    return raw;                        /* multiplicity 6 / 3! */
}

/* stamp a complex current into the RHS at the residual row's node, with the
 * sign convention diodisto.c uses */
static inline void stamp(CKTcircuit *ckt, const uint32_t *node_mapping,
                         uint32_t row, dcomplex v)
{
    uint32_t n = node_mapping[row];
    if (n == 0)
        return;                        /* ground row: nothing to stamp */
    ckt->CKTrhs[n] -= v.re;
    ckt->CKTirhs[n] -= v.im;
}

/* ------------------------------------------------------------------ driver */
extern int OSDIdisto(int mode, GENmodel *inModel, CKTcircuit *ckt)
{
    GENmodel *gen_model;
    GENinstance *gen_inst;
    DISTOAN *job = (DISTOAN *)ckt->CKTcurJob;

    OsdiRegistryEntry *entry = osdi_reg_entry_model(inModel);
    const OsdiDescriptor *descr = entry->descriptor;

    /* Enhancement-352: an .osdi built before OSDI 0.8 has no taylor fields at
     * all -- its descriptor simply ends earlier -- so reading them would run off
     * the end. Such a model contributes nothing to .disto, exactly as before. */
    if (getenv("OSDI_DISTO_DEBUG"))
        fprintf(stderr, "DISTODBG %s mode=%d taylor=%d n2=%u n3=%u\n",
                descr->name, mode, (int)entry->has_taylor,
                descr->num_taylor2, descr->num_taylor3);
    if (!entry->has_taylor)
        return OK;
    if (descr->num_taylor2 == 0 && descr->num_taylor3 == 0) {
        /* No tensors. Either the model is genuinely linear (fine, nothing to
         * add) or its nonlinearity is not reachable by the tensor pass. The
         * remaining unreachable case is a nonlinearity in a GROUND-REFERENCED
         * probe: the tensors are indexed by model input, and a bare V(a) is not
         * recorded as one because it has no hi/lo pair. ($limit used to sit here
         * too -- Enhancement-353 folds the limited values into the derivative
         * chain, so limiting models now contribute properly.) Whatever remains
         * must still be reported: registering DEVdisto removed the blanket
         * warning in cktdisto.c, and silently returning zero here would
         * reinstate exactly the quietly-wrong result Enhancement-62 added that
         * warning to prevent. Warn once per model, at setup. */
        if (mode == D_SETUP && descr->num_jacobian_entries > descr->num_nodes) {
            fprintf(stderr,
                "Warning: Verilog-A (OSDI) device '%s' contributes no distortion\n"
                "         tensors; .disto will NOT include its nonlinearities.\n"
                "         (A nonlinearity in a ground-referenced probe, which is\n"
                "         not a model input, falls in this case.)\n",
                descr->name);
        }
        return OK;
    }

    if (mode == D_SETUP)
        return OK;                     /* coefficients are read per mode below */

    /* grow the scratch buffers ([resist, react] pairs, stride 2) */
    if (t2_len < descr->num_taylor2) {
        t2_buf = TREALLOC(double, t2_buf, 2 * descr->num_taylor2);
        t2_len = descr->num_taylor2;
    }
    if (t3_len < descr->num_taylor3) {
        t3_buf = TREALLOC(double, t3_buf, 2 * descr->num_taylor3);
        t3_len = descr->num_taylor3;
    }

    for (gen_model = inModel; gen_model; gen_model = gen_model->GENnextModel) {
        void *model = osdi_model_data(gen_model);

        for (gen_inst = gen_model->GENinstances; gen_inst;
             gen_inst = gen_inst->GENnextInstance) {
            void *inst = osdi_instance_data(entry, gen_inst);
            const uint32_t *node_mapping =
                (const uint32_t *)(((const char *)inst) + descr->node_mapping_offset);

            if (descr->num_taylor2 && descr->load_taylor2)
                descr->load_taylor2(inst, model, t2_buf);
            if (descr->num_taylor3 && descr->load_taylor3)
                descr->load_taylor3(inst, model, t3_buf);

            /* Which kernel slots this mode needs. H1 = f1, H2 = f2 (conjugated
             * for the difference modes), K11 = 2f1, K1m2 = f1-f2. */
            const double *re1 = job->r1H1ptr, *im1 = job->i1H1ptr;
            const double *re2 = job->r1H2ptr, *im2 = job->i1H2ptr;
            const double *reK11 = job->r2H11ptr, *imK11 = job->i2H11ptr;
            const double *reK12 = job->r2H1m2ptr, *imK12 = job->i2H1m2ptr;

            /* Two passes: the resistive tensor, then the reactive one. The
             * reactive result is rotated by j*omega, exactly as diodisto.c does
             * (`temp += -omega*Im(...)`, `itemp += +omega*Re(...)`). */
            uint32_t pass;
            for (pass = 0; pass < 2; pass++) {
                double omega = ckt->CKTomega;
                if (pass == 1u && omega == 0.0)
                    continue;

                uint32_t e;
                /* ---- second-order contributions ---------------------------- */
                for (e = 0; e < descr->num_taylor2; e++) {
                    double raw = t2_buf[2 * e + pass];
                    if (raw == 0.0)
                        continue;
                    uint32_t row = descr->taylor2_entries[e].row;
                    uint32_t a = descr->taylor2_entries[e].col1;
                    uint32_t b = descr->taylor2_entries[e].col2;
                    double c2 = taylor_c2(raw, a, b);
                    dcomplex acc = cx(0.0, 0.0);

                    switch (mode) {
                    case D_TWOF1: {
                        dcomplex ha = input_kernel(descr, node_mapping, a, re1, im1);
                        dcomplex hb = input_kernel(descr, node_mapping, b, re1, im1);
                        acc = cmul(ha, hb);
                        break;
                    }
                    case D_THRF1: {
                        dcomplex ha = input_kernel(descr, node_mapping, a, re1, im1);
                        dcomplex hb = input_kernel(descr, node_mapping, b, re1, im1);
                        dcomplex ka = input_kernel(descr, node_mapping, a, reK11, imK11);
                        dcomplex kb = input_kernel(descr, node_mapping, b, reK11, imK11);
                        acc = cadd(cmul(ha, kb), cmul(hb, ka));
                        break;
                    }
                    case D_F1PF2:
                    case D_F1MF2: {
                        dcomplex ha = input_kernel(descr, node_mapping, a, re1, im1);
                        dcomplex hb = input_kernel(descr, node_mapping, b, re1, im1);
                        dcomplex ga = input_kernel(descr, node_mapping, a, re2, im2);
                        dcomplex gb = input_kernel(descr, node_mapping, b, re2, im2);
                        if (mode == D_F1MF2) {   /* -f2 -> conjugate */
                            ga = cconj(ga);
                            gb = cconj(gb);
                        }
                        /* The reference halves this: D1nF12 returns
                         * 0.5*S2vF12, and S2vF12 already sums both orderings.
                         * So the mixed-tone 2nd-order response is c*H1*H2, not
                         * 2*c*H1*H2 -- without the 0.5 both f1+f2 and f1-f2 come
                         * out exactly 2x, and the f1-f2 error then propagates
                         * into IM3 through the K1m2 kernel. */
                        acc = cscale(cadd(cmul(ha, gb), cmul(hb, ga)), 0.5);
                        break;
                    }
                    case D_2F1MF2: {
                        dcomplex ha = input_kernel(descr, node_mapping, a, re1, im1);
                        dcomplex hb = input_kernel(descr, node_mapping, b, re1, im1);
                        dcomplex ga = cconj(input_kernel(descr, node_mapping, a, re2, im2));
                        dcomplex gb = cconj(input_kernel(descr, node_mapping, b, re2, im2));
                        dcomplex ka = input_kernel(descr, node_mapping, a, reK11, imK11);
                        dcomplex kb = input_kernel(descr, node_mapping, b, reK11, imK11);
                        dcomplex qa = input_kernel(descr, node_mapping, a, reK12, imK12);
                        dcomplex qb = input_kernel(descr, node_mapping, b, reK12, imK12);
                        acc = cadd(cscale(cadd(cmul(ha, qb), cmul(hb, qa)), 2.0),
                                   cadd(cmul(ga, kb), cmul(gb, ka)));
                        acc = cscale(acc, 1.0 / 3.0);
                        break;
                    }
                    default:
                        continue;
                    }

                    acc = cscale(acc, c2);
                    if (pass == 1u)
                        acc = cx(-omega * acc.im, omega * acc.re);
                    stamp(ckt, node_mapping, row, acc);
                }

                /* ---- third-order contributions ----------------------------- */
                for (e = 0; e < descr->num_taylor3; e++) {
                    double raw = t3_buf[2 * e + pass];
                    if (raw == 0.0)
                        continue;
                    uint32_t row = descr->taylor3_entries[e].row;
                    uint32_t a = descr->taylor3_entries[e].col1;
                    uint32_t b = descr->taylor3_entries[e].col2;
                    uint32_t c = descr->taylor3_entries[e].col3;
                    double c3 = taylor_c3(raw, a, b, c);
                    dcomplex acc = cx(0.0, 0.0);

                    switch (mode) {
                    case D_THRF1: {
                        dcomplex ha = input_kernel(descr, node_mapping, a, re1, im1);
                        dcomplex hb = input_kernel(descr, node_mapping, b, re1, im1);
                        dcomplex hc = input_kernel(descr, node_mapping, c, re1, im1);
                        acc = cmul(cmul(ha, hb), hc);
                        break;
                    }
                    case D_2F1MF2: {
                        dcomplex ha = input_kernel(descr, node_mapping, a, re1, im1);
                        dcomplex hb = input_kernel(descr, node_mapping, b, re1, im1);
                        dcomplex hc = input_kernel(descr, node_mapping, c, re1, im1);
                        dcomplex ga = cconj(input_kernel(descr, node_mapping, a, re2, im2));
                        dcomplex gb = cconj(input_kernel(descr, node_mapping, b, re2, im2));
                        dcomplex gc = cconj(input_kernel(descr, node_mapping, c, re2, im2));
                        acc = cadd(cadd(cmul(cmul(ha, hb), gc), cmul(cmul(ha, hc), gb)),
                                   cmul(cmul(hc, hb), ga));
                        acc = cscale(acc, 1.0 / 3.0);
                        break;
                    }
                    default:
                        continue;      /* 3rd order contributes only to 3f1, 2f1-f2 */
                    }

                    acc = cscale(acc, c3);
                    if (pass == 1u)
                        acc = cx(-omega * acc.im, omega * acc.re);
                    stamp(ckt, node_mapping, row, acc);
                }
            }
        }
    }

    return OK;
}
