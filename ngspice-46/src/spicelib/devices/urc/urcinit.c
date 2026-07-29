#include "ngspice/config.h"

#include "ngspice/devdefs.h"

#include "urcitf.h"
#include "urcext.h"
#include "urcinit.h"


SPICEdev URCinfo = {
    .DEVpublic = {
        .name = "URC",
        .description = "Uniform R.C. line",
        .terms = &URCnSize,
        .numNames = &URCnSize,
        .termNames = URCnames,
        .numInstanceParms = &URCpTSize,
        .instanceParms = URCpTable,
        .numModelParms = &URCmPTSize,
        .modelParms = URCmPTable,
        .flags = 0,

#ifdef XSPICE
        .cm_func = NULL,
        .num_conn = 0,
        .conn = NULL,
        .num_param = 0,
        .param = NULL,
        .num_inst_var = 0,
        .inst_var = NULL,
#endif
    },

    .DEVparam = URCparam,
    .DEVmodParam = URCmParam,
    .DEVload = NULL,
    .DEVsetup = URCsetup,
    .DEVunsetup = URCunsetup,
    /* Enhancement-370: was `URCsetup`. URCsetup is a SUBCIRCUIT EXPANDER -- it
     * calls CKTmkVolt per lump and CKTcrtElt per element, with no idempotency
     * guard -- while CKTpzSetup calls DEVpzSetup for every device on EVERY pz
     * job. So each `.pz` re-expanded the URC, creating fresh internal nodes
     * AFTER NIinit had already sized the RHS for the previous node count; the
     * resistors of the new lump then indexed past CKTrhsOld (ASan:
     * heap-buffer-overflow READ in RESload, buffer allocated by NIreinit).
     *
     * The URC stamps nothing itself -- DEVload, DEVacLoad and DEVpzLoad are all
     * NULL -- so it needs no pz setup at all. The RES/CAP instances it creates
     * are ordinary circuit elements registered under their own device types, and
     * CKTpzSetup calls RESsetup/CAPsetup for them, which is what actually
     * re-binds the matrix entries after the pz matrix is rebuilt.
     *
     * (RESsetup/CAPsetup are safe as DEVpzSetup because they only allocate
     * matrix entries; URCsetup is the only expander wired up this way.) */
    .DEVpzSetup = NULL,
    .DEVtemperature = NULL,
    .DEVtrunc = NULL,
    .DEVfindBranch = NULL,
    .DEVacLoad = NULL,
    .DEVaccept = NULL,
    .DEVdestroy = NULL,
    .DEVmodDelete = NULL,
    .DEVdelete = NULL,
    .DEVsetic = NULL,
    .DEVask = URCask,
    .DEVmodAsk = URCmAsk,
    .DEVpzLoad = NULL,
    .DEVconvTest = NULL,
    .DEVsenSetup = NULL,
    .DEVsenLoad = NULL,
    .DEVsenUpdate = NULL,
    .DEVsenAcLoad = NULL,
    .DEVsenPrint = NULL,
    .DEVsenTrunc = NULL,
    .DEVdisto = NULL,
    .DEVnoise = NULL,
    .DEVsoaCheck = NULL,
    .DEVinstSize = &URCiSize,
    .DEVmodSize = &URCmSize,

#ifdef CIDER
    .DEVdump = NULL,
    .DEVacct = NULL,
#endif

#ifdef KLU
    .DEVbindCSC = NULL,
    .DEVbindCSCComplex = NULL,
    .DEVbindCSCComplexToReal = NULL,
#endif
};


SPICEdev *
get_urc_info(void)
{
    return &URCinfo;
}
