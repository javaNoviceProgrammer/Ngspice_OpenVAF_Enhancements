/**********
Enhancement-748 (Touchstone-import hunt F9): native n-port device -- noise.

A passive linear N-port at temperature T has the noise-current correlation
matrix  C(f) = 4kT * Re(Y(f))  between its ports (Bosma's theorem: the thermal
noise of a passive network is fixed by its admittance). The device had no noise
entry, so a block imported from a measured filter, package or cable contributed
nothing to `.noise`, and the noise figure of `.sp` through it was that of the
surrounding circuit only.

C is real symmetric, so it is decomposed once per frequency point into its
eigenvectors, C = sum_m lambda_m v_m v_m^T, and each term is one independent
source of density lambda_m injecting v_m[k] at port k against the reference --
which NevalSrcVec evaluates through the adjoint solve, in `.noise` and in the
S-parameter noise analysis alike. Re(Y) is symmetrized (a fit of a reciprocal
network is symmetric; the theorem is for passive blocks) and a negative
eigenvalue, which a non-passive fit can carry, is dropped: no source can be
negative. The device carries one summary source per instance, `onoise_<inst>`.
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/const.h"
#include "ngspice/iferrmsg.h"
#include "ngspice/noisedef.h"
#include "nportdefs.h"

extern void NPORTadmittance(NPORTmodel *, int, int, double, double,
                            double *, double *);

/* cyclic Jacobi on a real symmetric n x n matrix A (row-major, destroyed):
 * eigenvalues into w, eigenvectors into the COLUMNS of V (row-major) */
static void
nport_jacobi(int n, double *A, double *w, double *V)
{
    int i, j, k, sweep;
    for (i = 0; i < n; i++)
        for (j = 0; j < n; j++)
            V[i * n + j] = (i == j) ? 1.0 : 0.0;
    for (sweep = 0; sweep < 60; sweep++) {
        double off = 0.0, diag = 0.0;
        for (i = 0; i < n; i++) {
            diag += A[i * n + i] * A[i * n + i];
            for (j = i + 1; j < n; j++)
                off += A[i * n + j] * A[i * n + j];
        }
        if (off <= 1e-30 * (diag + 1e-300))
            break;
        for (i = 0; i < n - 1; i++) {
            for (j = i + 1; j < n; j++) {
                double aij = A[i * n + j], t, c, s, theta;
                if (aij == 0.0)
                    continue;
                theta = (A[j * n + j] - A[i * n + i]) / (2.0 * aij);
                t = (theta >= 0.0 ? 1.0 : -1.0) / (fabs(theta) + sqrt(theta * theta + 1.0));
                c = 1.0 / sqrt(t * t + 1.0);
                s = t * c;
                for (k = 0; k < n; k++) {          /* rotate rows/cols i, j */
                    double aki = A[k * n + i], akj = A[k * n + j];
                    A[k * n + i] = c * aki - s * akj;
                    A[k * n + j] = s * aki + c * akj;
                }
                for (k = 0; k < n; k++) {
                    double aik = A[i * n + k], ajk = A[j * n + k];
                    A[i * n + k] = c * aik - s * ajk;
                    A[j * n + k] = s * aik + c * ajk;
                }
                for (k = 0; k < n; k++) {
                    double vki = V[k * n + i], vkj = V[k * n + j];
                    V[k * n + i] = c * vki - s * vkj;
                    V[k * n + j] = s * vki + c * vkj;
                }
            }
        }
    }
    for (i = 0; i < n; i++)
        w[i] = A[i * n + i];
}

int
NPORTnoise(int mode, int operation, GENmodel *genmodel, CKTcircuit *ckt,
           Ndata *data, double *OnDens)
{
    NOISEAN *job = (NOISEAN *) ckt->CKTcurJob;
    NPORTmodel *model;
    NPORTinstance *inst;
    double noizDens, lnNdens, tempOutNoise, tempInNoise;

    for (model = (NPORTmodel *) genmodel; model; model = NPORTnextModel(model)) {
        int N = model->NPORTnPorts;
        for (inst = NPORTinstances(model); inst; inst = NPORTnextInstance(inst)) {
            switch (operation) {

            case N_OPEN:
                if (job->NStpsSm != 0) {
                    switch (mode) {
                    case N_DENS:
                        NOISE_ADD_OUTVAR(ckt, data, "onoise_%s%s", inst->NPORTname, "");
                        break;
                    case INT_NOIZ:
                        NOISE_ADD_OUTVAR(ckt, data, "onoise_total_%s%s", inst->NPORTname, "");
                        NOISE_ADD_OUTVAR(ckt, data, "inoise_total_%s%s", inst->NPORTname, "");
                        break;
                    }
                }
                break;

            case N_CALC:
                switch (mode) {

                case N_DENS: {
                    double w = 2.0 * M_PI * data->freq;
                    double kT4 = 4.0 * CONSTboltz * ckt->CKTtemp;
                    int *node = GENnode(&inst->gen);
                    int ref = node[N];
                    double *C = TMALLOC(double, (size_t) N * N);
                    double *V = TMALLOC(double, (size_t) N * N);
                    double *lam = TMALLOC(double, N);
                    double *amp = TMALLOC(double, N);
                    int i, j, m;

                    for (i = 0; i < N; i++) {
                        for (j = 0; j < N; j++) {
                            double yr, yi;
                            NPORTadmittance(model, i, j, 0.0, w, &yr, &yi);
                            C[i * N + j] = yr;
                        }
                    }
                    for (i = 0; i < N; i++)             /* symmetrize, scale */
                        for (j = i; j < N; j++) {
                            double c = 0.5 * kT4 * (C[i * N + j] + C[j * N + i]);
                            C[i * N + j] = C[j * N + i] = c;
                        }
                    nport_jacobi(N, C, lam, V);
                    noizDens = 0.0;
                    for (m = 0; m < N; m++) {
                        double nm;
                        if (!(lam[m] > 0.0))
                            continue;                   /* a non-passive fit's negative share: no source */
                        for (i = 0; i < N; i++)
                            amp[i] = V[i * N + m];
                        NevalSrcVec(&nm, NULL, ckt, N, node, ref, amp, lam[m]);
                        noizDens += nm;
                    }
                    tfree(C);
                    tfree(V);
                    tfree(lam);
                    tfree(amp);
                    lnNdens = log(MAX(noizDens, N_MINLOG));
                    *OnDens += noizDens;

                    if (data->delFreq == 0.0) {
                        inst->NPORTnVar[LNLSTDENS] = lnNdens;
                        if (data->freq == job->NstartFreq) {
                            inst->NPORTnVar[OUTNOIZ] = 0.0;
                            inst->NPORTnVar[INNOIZ] = 0.0;
                        }
                    } else {
                        tempOutNoise = Nintegrate(noizDens, lnNdens, inst->NPORTnVar[LNLSTDENS], data);
                        tempInNoise = Nintegrate(noizDens * data->GainSqInv, lnNdens + data->lnGainInv,
                                                 inst->NPORTnVar[LNLSTDENS] + data->lnGainInv, data);
                        inst->NPORTnVar[LNLSTDENS] = lnNdens;
                        data->outNoiz += tempOutNoise;
                        data->inNoise += tempInNoise;
                        if (job->NStpsSm != 0) {
                            inst->NPORTnVar[OUTNOIZ] += tempOutNoise;
                            inst->NPORTnVar[INNOIZ] += tempInNoise;
                        }
                    }
                    if (data->prtSummary)
                        data->outpVector[data->outNumber++] = noizDens;
                    break;
                }

                case INT_NOIZ:
                    if (job->NStpsSm != 0) {
                        data->outpVector[data->outNumber++] = inst->NPORTnVar[OUTNOIZ];
                        data->outpVector[data->outNumber++] = inst->NPORTnVar[INNOIZ];
                    }
                    break;
                }
                break;

            case N_CLOSE:
                return OK;
            }
        }
    }
    return OK;
}
