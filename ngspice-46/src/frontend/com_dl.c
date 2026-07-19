#include "ngspice/ngspice.h" /* for wl */
#include "ngspice/ftedefs.h"
#include "ngspice/devdefs.h" /* solve deps in dev.h*/
#include "../spicelib/devices/dev.h" /* for load library commands */
#include "com_dl.h"


#ifdef XSPICE
void com_codemodel(wordlist *wl)
{
if (wl && wl->wl_word)
#ifdef CM_TRACE
    fprintf(stdout, "Note: loading codemodel %s\n", ww->wl_word);
#endif
    if (load_opus(wl->wl_word)) {
        fprintf(stderr, "Error: Library %s couldn't be loaded!\n", wl->wl_word);
        ft_spiniterror = TRUE;
        ft_codemodelerror = TRUE;
        if (ft_stricterror) /* if set in spinit */
            controlled_exit(EXIT_BAD);
    }
#ifdef CM_TRACE
    else {
        fprintf(stdout, "Codemodel %s is loaded\n", wl->wl_word);
    }
#endif
}
#endif

#ifdef OSDI
/* `pre_osdi [-f] file.osdi ...` -- load one or more OSDI object files.
 * Enhancement-229: a leading `-f` (or `-force`) forces a reload of an already-
 * loaded file, so an edit -> recompile -> re-source loop picks up the new model
 * without restarting ngspice (a plain re-load is skipped, since the device type
 * is already registered). */
void com_osdi(wordlist *wl)
{
    wordlist *ww;
    bool force = FALSE;
    /* a `-f`/`-force` anywhere in the argument list applies to every file */
    for (ww = wl; ww; ww = ww->wl_next)
        if (eq(ww->wl_word, "-f") || eq(ww->wl_word, "-force"))
            force = TRUE;
    for (ww = wl; ww; ww = ww->wl_next) {
        if (eq(ww->wl_word, "-f") || eq(ww->wl_word, "-force"))
            continue;
        if (load_osdi(ww->wl_word, force)) {
            fprintf(cp_err, "Error: Library %s couldn't be loaded!\n", ww->wl_word);
            ft_spiniterror = TRUE;
            ft_osdierror = TRUE;
            if (ft_stricterror)
                controlled_exit(EXIT_BAD);
         }
    }
}
#endif




#ifdef DEVLIB
void com_use(wordlist *wl)
{
    wordlist *ww;
    for (ww = wl; ww; ww = ww->wl_next)
        if (load_dev(wl->wl_word))
            fprintf(cp_err, "Error: Library %s couldn't be loaded!\n", ww->wl_word);
}
#endif
