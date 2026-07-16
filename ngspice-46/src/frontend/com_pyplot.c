/* Enhancement-94: the 'pyplot' command -- plot vectors via matplotlib.
   Like com_gnuplot(), but the output file base name is OPTIONAL (E-95): the
   first word is treated as a file name only when it is not itself a plot
   expression (it contains no '(' and does not name a vector); otherwise the
   base name defaults to "pyplot" and every word is a plot argument. */

#include <stddef.h>
#include <string.h>

#include "ngspice/ngspice.h"
#include "ngspice/bool.h"
#include "ngspice/wordlist.h"
#include "ngspice/fteext.h"

#include "plotting/plotit.h"
#include "plotting/pyplot.h" /* ft_pyplot_eye() */
#include "../misc/mktemp.h"
#include "../misc/util.h" /* ngdirname() */

#include "com_pyplot.h"
#include "com_eye.h" /* com_eye() -- for the -eye flag (Enhancement-208) */


/* matplotlib [file] plotargs */
void
com_pyplot(wordlist *wl)
{
    char *fname = NULL;
    char *fullname = NULL;
    char defname[64] = "pyplot";
    bool tempf = FALSE;
    /* Enhancement-183: successive default-named plots must get DISTINCT base
       names. In window (interactive) mode pyplot launches the Python viewer in
       the BACKGROUND, so two plots that share the "pyplot" base race on the
       same pyplot.py/pyplot.data: the second call overwrites the files before
       the first viewer has read them, and both windows end up showing the
       second plot (its title, its data). A per-session counter keeps the first
       default plot named "pyplot" (unchanged) and names later ones
       "pyplot-2", "pyplot-3", ... so each viewer reads its own files. */
    static unsigned int autoseq = 0;
    /* Enhancement-208: `pyplot [name] -eye <expr> -ui <T> [opts]` renders an eye
       diagram. `eye_args` (set when a -eye marker is found) points at the `eye`
       command's own arguments -- the expression and its flags. */
    bool is_eye = FALSE;
    wordlist *eye_args = NULL;

    if (!wl)
        return;

    /* E-208: detect the -eye marker anywhere in the argument list; the tokens
       after it belong to the `eye` command. A single bare token before -eye is
       taken as the output base name (`pyplot myeye -eye v(rx) -ui 0.5n`). */
    {
        wordlist *w, *marker = NULL;
        for (w = wl; w; w = w->wl_next)
            if (w->wl_word && eq(w->wl_word, "-eye")) { marker = w; break; }
        if (marker) {
            is_eye = TRUE;
            strcpy(defname, "eye");
            if (wl != marker && wl->wl_word)
                fname = wl->wl_word;
            eye_args = marker->wl_next;
            if (!eye_args || !eye_args->wl_word) {
                fprintf(cp_err, "Usage: pyplot [name] -eye <expr> -ui <T> "
                        "[-tstart t0] [-threshold vth] [-window frac]\n");
                return;
            }
        }
    }

    /* The first word is an output file name only if it is not itself a plot
       expression -- i.e. it has no '(' (as in v(out), db(...)) and does not
       name an existing vector (as a bare node name would). Otherwise the base
       name defaults to "pyplot" and all words are plot arguments. */
    if (!is_eye) {
        const char *w = wl->wl_word;
        bool is_expr = (strchr(w, '(') != NULL) || (vec_get(w) != NULL);
        if (!is_expr) {
            fname = wl->wl_word;
            wl = wl->wl_next;
        }
    }

    if (!fname) {
        if (autoseq > 0)
            (void) snprintf(defname, sizeof defname, "%s-%u",
                            is_eye ? "eye" : "pyplot", autoseq + 1);
        autoseq++;
        fname = defname;
    }

    if (cieq(fname, "temp") || cieq(fname, "tmp")) {
        fname = smktemp("py");
        tempf = TRUE;
    }

    /* Enhancement-183: write the .py/.data (and the .png) next to the CIRCUIT
       FILE, not in whatever directory ngspice happens to have been started
       from -- so a self-contained deck folder collects its own plot artifacts.
       Only when the user gave a bare base name (their own path, if any, is
       respected) and we know where the deck came from; a bare relative deck
       name (ci_filename dir == ".") is left in the cwd, exactly as before. */
    if (!tempf && ft_curckt && ft_curckt->ci_filename &&
            strchr(fname, DIR_TERM) == NULL && strchr(fname, '/') == NULL) {
        char *dir = ngdirname(ft_curckt->ci_filename);
        if (dir && dir[0] && !(dir[0] == '.' && dir[1] == '\0')) {
            fullname = tprintf("%s%s%s", dir, DIR_PATHSEP, fname);
            fname = fullname;
        }
        tfree(dir);
    }

    /* Enhancement-208: run the `eye` analysis (it folds the waveform and leaves
       eye_wave/eye_t + the scalar metrics in a fresh current 'eye' plot), then
       render that folded eye as a matplotlib eye diagram. */
    if (is_eye) {
        com_eye(eye_args);
        ft_pyplot_eye(fname, eye_args->wl_word);
        goto done;
    }

    if (!wl) /* no plot arguments left */
        goto done;

    (void) plotit(wl, fname, "pyplot");

done:
    if (tempf)
        tfree(fname);
    if (fullname)
        tfree(fullname);
}
