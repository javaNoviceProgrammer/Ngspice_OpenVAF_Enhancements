#include "ngspice/ngspice.h" /* for wl */
#include "ngspice/ftedefs.h"
#include "ngspice/devdefs.h" /* solve deps in dev.h*/
#include "../spicelib/devices/dev.h" /* for load library commands */
#include "com_dl.h"

#ifdef OSDI
#include "ngspice/osdiitf.h"
#include <sys/types.h>
#include <sys/stat.h>
#include <errno.h>
/* `_WIN32` rather than `__MINGW32__`/`_MSC_VER`: it is defined by every Windows
 * toolchain this tree is built with, including MinGW-w64 in 64-bit mode. mkdir()
 * takes a mode on POSIX and does not exist under that name on Windows, where
 * _mkdir() is supplied by <direct.h> for both MSVC and MinGW. `stat`/`st_mtime`
 * need no such treatment -- inpcom.c has used them through <sys/stat.h> on all
 * three platforms for years. */
#if defined(_WIN32)
#include <direct.h>
#define NG_MKDIR(p) _mkdir(p)
#else
#define NG_MKDIR(p) mkdir((p), 0777)
#endif
#endif


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
/* ---- Enhancement-500: `pre_osdi -va file.va ...` ------------------------
 *
 * Compile Verilog-A and load the result in one step, so a deck that ships its
 * own models needs no separate build. The generated objects are collected in an
 * `osdi/` directory beside the netlist rather than scattered next to each
 * source, which keeps a model directory clean and -- not incidentally -- makes
 * it impossible for the output path to collide with the input: Enhancement-452
 * recorded `openvaf-r m.va -o m.va` DESTROYING the source and exiting 0.
 *
 * RECOMPILING IS THE DEFAULT, and `.option osdicache` opts out. The usual
 * instinct is the other way round, but a `.va` timestamp only says whether the
 * SOURCE changed; while openvaf-r itself is under development the compiler
 * changes far more often than the models do, and a skipped rebuild then loads
 * an object built by a compiler that no longer exists. That is the shape of
 * Enhancement-453, whose cache key omitted its own codegen settings.
 * `-f` bypasses the cache outright, for the same reason. */

static int va_mtime(const char *p, time_t *t)
{
    struct stat st;
    if (stat(p, &st) != 0)
        return 0;
    *t = st.st_mtime;
    return 1;
}


/* basename without directory or extension */
static void va_stem(const char *path, char *out, size_t outlen)
{
    const char *b = path, *p, *dot;
    size_t n;
    for (p = path; *p; p++)
        if (*p == '/' || *p == '\\')
            b = p + 1;
    dot = strrchr(b, '.');
    n = dot ? (size_t) (dot - b) : strlen(b);
    if (n >= outlen)
        n = outlen - 1;
    memcpy(out, b, n);
    out[n] = '\0';
}


/* Compile `va` into <netlist dir>/osdi/<stem>.osdi. Returns a malloc'd path to
 * load, or NULL if the compile failed (already reported). */
static char *va_compile(const char *va, bool force)
{
    char dir[1024], outdir[1100], stem[256], osdi[1400], src[1400];
    char *ovf, *cmd;
    size_t cmdlen;
    int rc;
    time_t tva, tosdi;

    /* inputdir is the netlist's directory, and inp.c sets it around exactly the
       pre_ commands (it is NULL again afterwards). Fall back to the working
       directory for an interactive session or a deck read from stdin. */
    if (inputdir && inputdir[0])
        (void) snprintf(dir, sizeof dir, "%s", inputdir);
    else
        (void) snprintf(dir, sizeof dir, ".");

    (void) snprintf(outdir, sizeof outdir, "%s/osdi", dir);
    if (NG_MKDIR(outdir) != 0 && errno != EEXIST) {
        /* a read-only tree (a shared PDK, a CI checkout) must not be fatal:
           fall back beside the netlist and say which directory was used. */
        fprintf(cp_err, "pre_osdi: cannot create %s (%s); writing beside the "
                        "netlist instead\n", outdir, strerror(errno));
        (void) snprintf(outdir, sizeof outdir, "%s", dir);
    }

    va_stem(va, stem, sizeof stem);
    (void) snprintf(osdi, sizeof osdi, "%s/%s.osdi", outdir, stem);

    /* The SOURCE is named relative to the netlist, not to the working
       directory -- `ngspice -b sub/deck.cir` must find `sub/rmod.va` from a
       `pre_osdi -va rmod.va` inside it. load_osdi() already resolves its own
       argument that way; do the same here rather than leaving the two halves of
       one command disagreeing about what a relative path means. */
    if (va[0] == '/' || va[0] == '\\' ||
        (va[0] && va[1] == ':') || !(inputdir && inputdir[0]))
        (void) snprintf(src, sizeof src, "%s", va);
    else
        (void) snprintf(src, sizeof src, "%s/%s", inputdir, va);

    /* Enhancement-452: never let the object path be the source path. */
    if (strcmp(osdi, src) == 0) {
        fprintf(cp_err, "pre_osdi: refusing to compile %s onto itself\n", va);
        return NULL;
    }

    /* `-f` forces the REBUILD as well as the reload. Enhancement-229 added the
       flag so that an edit -> recompile -> re-source loop picks the new model
       up without restarting ngspice; under `-va` the compile is part of that
       loop, so honouring `-f` for the load alone would reload the very object
       the user is trying to replace -- the one case the flag exists for. */
    if (!force && osdi_va_cache && va_mtime(osdi, &tosdi) && va_mtime(src, &tva) &&
        tosdi > tva) {
        /* strictly newer, not `>=`: st_mtime has one-second granularity, so an
           edit and a re-run inside the same second would otherwise load the
           object built from the PREVIOUS text. A tie costs one needless
           recompile; the other way costs a wrong answer. */
        fprintf(cp_out, "pre_osdi: %s is up to date (.option osdicache)\n", osdi);
        return copy(osdi);
    }

    /* Say which file is missing rather than leaving the compiler to report it
       as an exit status: `openvaf-r failed (exit 512)` names neither the cause
       nor the fix. */
    if (!va_mtime(src, &tva)) {
        fprintf(cp_err, "pre_osdi: no such Verilog-A source: %s\n", src);
        return NULL;
    }

    ovf = osdi_find_openvaf();
    cmdlen = strlen(ovf) + strlen(src) + strlen(osdi) + 32;
    cmd = TMALLOC(char, cmdlen);
    (void) snprintf(cmd, cmdlen, "\"%s\" \"%s\" -o \"%s\"", ovf, src, osdi);
    rc = system(cmd);
    tfree(cmd);
    /* Enhancement-510: `system()` returns a WAIT STATUS, not an exit code, so
       the compiler's 101 was reported as 25856 (101 << 8) and a 2 as 512. The
       comment above this block quotes "exit 512" as if it were an exit code,
       which is exactly that encoding gone unnoticed. Decode it, and name a
       signal death as such rather than printing a status word. */
#ifdef WIFEXITED
    if (rc != -1 && WIFEXITED(rc))
        rc = WEXITSTATUS(rc);
    else if (rc != -1 && WIFSIGNALED(rc)) {
        fprintf(cp_err, "pre_osdi: openvaf-r was killed by signal %d compiling %s.\n",
                WTERMSIG(rc), src);
        return NULL;
    }
#endif
    if (rc != 0) {
        fprintf(cp_err, "pre_osdi: openvaf-r failed (exit %d) compiling %s.\n"
                        "  Set the compiler with `set openvaf=/path/to/openvaf-r`, the OPENVAF\n"
                        "  environment variable, or put openvaf-r in $SPICE_LIB_DIR or PATH.\n",
                rc, src);
        tfree(ovf);
        return NULL;
    }
    tfree(ovf);
    fprintf(cp_out, "pre_osdi: %s -> %s\n", src, osdi);
    return copy(osdi);
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
    bool va = FALSE;                          /* Enhancement-500 */
    /* a `-f`/`-force` anywhere in the argument list applies to every file */
    for (ww = wl; ww; ww = ww->wl_next) {
        if (eq(ww->wl_word, "-f") || eq(ww->wl_word, "-force"))
            force = TRUE;
        else if (eq(ww->wl_word, "-va"))
            va = TRUE;                        /* Enhancement-500 */
    }
    for (ww = wl; ww; ww = ww->wl_next) {
        const char *file = ww->wl_word;
        char *built = NULL;
        if (eq(file, "-f") || eq(file, "-force") || eq(file, "-va"))
            continue;
        /* Enhancement-500: under `-va`, a Verilog-A source is compiled first and
           the object it produces is what gets loaded. Anything that is not a
           `.va` is still taken as an object, so `pre_osdi -va *.va extra.osdi`
           does the obvious thing. */
        if (va) {
            const char *dot = strrchr(file, '.');
            if (dot && cieq(dot, ".va")) {
                built = va_compile(file, force);
                if (!built) {
                    ft_spiniterror = TRUE;
                    ft_osdierror = TRUE;
                    if (ft_stricterror)
                        controlled_exit(EXIT_BAD);
                    continue;
                }
                file = built;
            }
        }
        if (load_osdi(file, force)) {
            fprintf(cp_err, "Error: Library %s couldn't be loaded!\n", file);
            ft_spiniterror = TRUE;
            ft_osdierror = TRUE;
            if (ft_stricterror)
                controlled_exit(EXIT_BAD);
         }
        if (built)
            tfree(built);
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
