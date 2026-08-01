/**********
Enhancement-242: native n-port device -- instance parameter parsing.
The n-port has no instance parameters (all data comes from the .model fit file),
so this only exists to satisfy the PARSECALL path for `N` instances.
**********/

#include "ngspice/ngspice.h"
#include "ngspice/ifsim.h"
#include "nportdefs.h"
#include "ngspice/sperror.h"

int
NPORTparam(int param, IFvalue *value, GENinstance *inst, IFvalue *select)
{
    NG_IGNORE(select);

    switch (param) {
    case NPORT_M:
        /* Enhancement-394: the subcircuit multiplier is now appended to every
           N line so that OSDI devices inside a multiplied subcircuit scale
           (they never did before). The n-port shares the N dispatcher but has
           no multiplier: its stamps run through a stateful convolution whose
           scaling is not a one-line change, and no finding in this release
           concerns it. Accept the parameter so the appended `m={m}` parses,
           and REPORT when it would have mattered -- previously the multiplier
           was dropped for n-ports in silence, exactly the same defect class
           this release is fixing elsewhere. */
        if (value->rValue != 1.0)
            fprintf(stderr,
                    "Warning: %s: n-port devices do not implement the "
                    "multiplier m=%g; it is ignored.\n",
                    inst->GENname, value->rValue);
        return OK;
    default:
        NG_IGNORE(value);
        NG_IGNORE(inst);
        return E_BADPARM;
    }
}
