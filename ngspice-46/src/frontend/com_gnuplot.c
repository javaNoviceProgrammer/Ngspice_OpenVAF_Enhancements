#include <stddef.h>

#include "ngspice/ngspice.h"
#include "ngspice/bool.h"
#include "ngspice/wordlist.h"
#include "ngspice/cpdefs.h"

#include "plotting/plotit.h"
#include "../misc/mktemp.h"

#include "com_gnuplot.h"


/* gnuplot file plotargs */
void
com_gnuplot(wordlist *wl)
{
    char *fname = NULL;
    bool tempf = FALSE;

    if (wl) {
        fname = wl->wl_word;
        wl = wl->wl_next;
    }

    if (!wl)
        return;

    if (cieq(fname, "temp") || cieq(fname, "tmp")) {
        fname = smktemp("gp"); /* Is this the correct name ? */
        tempf = TRUE;
    }

    (void) plotit(wl, fname, "gnuplot");

    /* Leave temp file sitting around so gnuplot can grab it from
       background. */
    if (tempf)
        tfree(fname);
}


/* data printout to file plotargs */
void
com_write_simple(wordlist *wl)
{
    char *fname = NULL;
    bool tempf = FALSE;
    bool csv = FALSE, had_csv = FALSE;
    wordlist *w, *csvnode = NULL;

    /* Optional -csv flag, in any position: `wrdata -csv file vec...` (or with
       -csv anywhere) is a per-call alias for `set wr_csv` -- comma-separated
       columns with a header row.  plotit() copies its wordlist, so we can
       splice the flag node out for the duration of the call and relink it
       afterwards, leaving the caller's original wordlist intact to free. */
    for (w = wl; w; w = w->wl_next)
        if (w->wl_word && eq(w->wl_word, "-csv")) {
            csvnode = w;
            break;
        }
    if (csvnode) {
        csv = TRUE;
        if (csvnode == wl)                    /* it was the head */
            wl = csvnode->wl_next;
        if (csvnode->wl_prev)
            csvnode->wl_prev->wl_next = csvnode->wl_next;
        if (csvnode->wl_next)
            csvnode->wl_next->wl_prev = csvnode->wl_prev;
    }

    if (wl) {
        fname = wl->wl_word;
        wl = wl->wl_next;
    }

    if (wl) {
        if (cieq(fname, "temp") || cieq(fname, "tmp")) {
            fname = smktemp("gp"); /* Is this the correct name ? */
            tempf = TRUE;
        }

        /* Enable CSV output for this write only, then restore the prior state
           so the flag doesn't leak into the global variable set. */
        if (csv) {
            had_csv = cp_getvar("wr_csv", CP_BOOL, NULL, 0);
            if (!had_csv) {
                bool yes = TRUE;
                cp_vset("wr_csv", CP_BOOL, &yes);
            }
        }

        (void) plotit(wl, fname, "writesimple");

        if (csv && !had_csv)
            cp_remvar("wr_csv");

        /* Leave temp file sitting around so gnuplot can grab it from
           background. */
        if (tempf)
            tfree(fname);
    }

    /* Relink the spliced-out -csv node so the caller frees the whole list. */
    if (csvnode) {
        if (csvnode->wl_prev)
            csvnode->wl_prev->wl_next = csvnode;
        if (csvnode->wl_next)
            csvnode->wl_next->wl_prev = csvnode;
    }
}
