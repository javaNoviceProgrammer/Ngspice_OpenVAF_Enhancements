/**********
Enhancement-747 (Touchstone-import hunt F7): native n-port device -- pole-zero load.

The device had a pz setup (its ordinary setup) but no pz load, so the
pole-zero matrix never held the block: a `pz` on a circuit with a native
n-port hung its output node on whatever else touched it and gave up with
"pz simulation(s) aborted" and no other word. The stamp is the AC one with the
analysis's complex frequency s in place of jw -- NPORTadmittance already takes
s = sre + j*sim -- into the (ptr, ptr+1) real/imaginary slots the pz analysis
reads, the convention of the built-in RLC pz loads.
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/complex.h"
#include "nportdefs.h"
#include "ngspice/sperror.h"

extern void NPORTadmittance(NPORTmodel *, int, int, double, double,
                            double *, double *);

int
NPORTpzLoad(GENmodel *inModel, CKTcircuit *ckt, SPcomplex *s)
{
    NPORTmodel *model = (NPORTmodel *)inModel;
    NPORTinstance *here;
    int i, j, N;

    NG_IGNORE(ckt);

    for (; model; model = NPORTnextModel(model)) {
        N = model->NPORTnPorts;
        for (here = NPORTinstances(model); here; here = NPORTnextInstance(here)) {
            for (i = 0; i < N; i++) {
                for (j = 0; j < N; j++) {
                    double yr, yi;
                    NPORTadmittance(model, i, j, s->real, s->imag, &yr, &yi);
                    *(here->NPORTyPtr[i * N + j])     += yr;
                    *(here->NPORTyPtr[i * N + j] + 1) += yi;
                    *(here->NPORTyColPtr[i])          += -yr;
                    *(here->NPORTyColPtr[i] + 1)      += -yi;
                    *(here->NPORTyRowPtr[j])          += -yr;
                    *(here->NPORTyRowPtr[j] + 1)      += -yi;
                    *(here->NPORTyRefPtr)             += yr;
                    *(here->NPORTyRefPtr + 1)         += yi;
                }
            }
        }
    }
    return OK;
}
