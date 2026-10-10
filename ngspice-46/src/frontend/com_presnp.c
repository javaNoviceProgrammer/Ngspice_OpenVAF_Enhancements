/* Enhancement-200: the `pre_snp` control command.
 *
 * `pre_snp <file.sNp> [module]` converts a Touchstone S-parameter file to a
 * Verilog-A n-port model (via snp2va_convert, the C port of snp2va.py) and then
 * invokes openvaf-r to compile it, producing <file>.osdi next to the source --
 * so `pre_osdi <file>.osdi` then loads it, symmetric with the existing flow.
 * The `.va`/`.osdi` are written beside the `.sNp` with the same base name.
 *
 * openvaf-r is located via, in order: the `openvaf` ngspice variable, the
 * OPENVAF environment variable, $SPICE_LIB_DIR/openvaf-r (the prebuilt bin
 * bundle keeps it there), then PATH.
 */
#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/cpextern.h"

#include "snp2va.h"
#include "ngspice/osdiitf.h"   /* Enhancement-827 */

#include <sys/stat.h>
#ifndef _WIN32
#include <sys/wait.h>     /* Enhancement-827: WIFEXITED */
#endif

static int file_exists(const char *p)
{
    struct stat st;
    return stat(p, &st) == 0;
}

/* Locate the openvaf-r compiler. Returns a malloc'd string (copy()).
 * Enhancement-500: exported (was static) so `pre_osdi -va` uses the same
 * lookup policy rather than inventing a second one. */
char *osdi_find_openvaf(void)
{
    char var[1024];
    char *e;
    if (cp_getvar("openvaf", CP_STRING, var, sizeof var) && var[0])
        return copy(var);
    e = getenv("OPENVAF");
    if (e && e[0])
        return copy(e);
    e = getenv("SPICE_LIB_DIR");
    if (e && e[0]) {
        char buf[1200];
        (void) snprintf(buf, sizeof buf, "%s/openvaf-r", e);
        if (file_exists(buf))
            return copy(buf);
    }
    return copy("openvaf-r");                       /* rely on PATH */
}

/* Enhancement-574: a compiler named without a directory -- the PATH fallback
 * of osdi_find_openvaf() -- is located on PATH the way system() will locate
 * it, so that its timestamp can be read for the staleness test above. Without
 * this the compiler check of Enhancement-573 was silently inert for exactly
 * the users it was written for: a `set openvaf=` or $OPENVAF names a path, a
 * bare `openvaf-r` on PATH could not be stat'ed and was not checked, and the
 * same deck cached or rebuilt depending on how the compiler had been named.
 * Returns 0 when the name is nowhere on PATH; the compile then fails and says
 * so itself. A name with a directory is returned as it is, unchecked.
 * Enhancement-827: moved here from com_dl.c and exported, beside
 * osdi_find_openvaf(), for osdi_report_compile_failure() below. */
int osdi_resolve_on_path(const char *name, char *out, size_t outlen)
{
    const char *path, *p;
#ifdef _WIN32
    const char sep = ';';
#else
    const char sep = ':';
#endif

    if (strchr(name, '/') || strchr(name, '\\') || (name[0] && name[1] == ':')) {
        (void) snprintf(out, outlen, "%s", name);
        return 1;
    }
    path = getenv("PATH");
    if (!path)
        return 0;
    for (p = path;;) {
        const char *e = strchr(p, sep);
        size_t n = e ? (size_t) (e - p) : strlen(p);
        struct stat st;
        if (n) {
            (void) snprintf(out, outlen, "%.*s/%s", (int) n, p, name);
            if (stat(out, &st) == 0)
                return 1;
#ifdef _WIN32
            (void) snprintf(out, outlen, "%.*s/%s.exe", (int) n, p, name);
            if (stat(out, &st) == 0)
                return 1;
#endif
        }
        if (!e)
            break;
        p = e + 1;
    }
    return 0;
}


/* Enhancement-827 (hunt 2026-10-08 F11): why a compile failed. Both generators
 * answered every failure with advice on where to put the compiler -- "Set the
 * compiler with `set openvaf=...`, the OPENVAF environment variable, or put
 * openvaf-r in $SPICE_LIB_DIR or PATH" -- including a compiler that was found,
 * ran, and printed the source's error just above (exit 65). The advice belongs
 * to a compiler that could not be run: not on PATH, no such file (the shell's
 * 127, cmd's 9009), not executable (126). A compiler that ran gets its exit
 * code and is pointed at its own messages; a Rust panic (101) is named as the
 * compiler's internal error; a signal is named as such. `status` is what
 * system() returned: a wait status where WIFEXITED exists (Enhancement-510
 * decoded it in pre_osdi; pre_snp printed the raw word, 16640 for 65). */
void osdi_report_compile_failure(const char *who, int status, const char *ovf,
                                 const char *src)
{
    int rc = status;
    char where[1400];
    int found;
    struct stat st;

#ifdef WIFEXITED
    if (status != -1 && WIFSIGNALED(status)) {
        fprintf(cp_err, "%s: %s was killed by signal %d compiling %s.\n",
                who, ovf, WTERMSIG(status), src);
        return;
    }
    if (status != -1 && WIFEXITED(status))
        rc = WEXITSTATUS(status);
#endif
    found = osdi_resolve_on_path(ovf, where, sizeof where) &&
            stat(where, &st) == 0;
#ifdef _WIN32
    if (!found && osdi_resolve_on_path(ovf, where, sizeof where - 4)) {
        strcat(where, ".exe");          /* a path named without its .exe */
        found = stat(where, &st) == 0;
    }
#endif
    if (status == -1 || !found || rc == 126 || rc == 127 || rc == 9009) {
        bool named_path = strchr(ovf, '/') || strchr(ovf, '\\') ||
                          (ovf[0] && ovf[1] == ':');
        fprintf(cp_err, "%s: could not run the compiler %s%s.\n"
                        "  Set the compiler with `set openvaf=/path/to/openvaf-r`, the OPENVAF\n"
                        "  environment variable, or put openvaf-r in $SPICE_LIB_DIR or PATH.\n",
                who, ovf,
                !found ? (named_path ? " (no such file)" : " (not on PATH)")
                       : rc == 126 ? " (not executable)" : "");
    } else if (rc == 101) {
        fprintf(cp_err, "%s: %s stopped on an internal error (exit 101) compiling %s;\n"
                        "  its message is above.\n", who, ovf, src);
    } else {
        fprintf(cp_err, "%s: %s could not compile %s (exit %d); its messages above\n"
                        "  say why.\n", who, ovf, src, rc);
    }
}

/* base = basename(snp) with the extension dropped; sanitized to a Verilog id. */
static void derive_module(const char *snp, char *mod, size_t modlen)
{
    const char *base = strrchr(snp, '/');
#ifdef _WIN32
    const char *bs = strrchr(snp, '\\');
    if (bs && (!base || bs > base)) base = bs;
#endif
    base = base ? base + 1 : snp;
    size_t i = 0;
    for (; base[i] && base[i] != '.' && i + 6 < modlen; i++) {
        char c = base[i];
        mod[i] = (isalnum((unsigned char) c) || c == '_') ? c : '_';
    }
    mod[i] = '\0';
    if (i == 0 || isdigit((unsigned char) mod[0])) {   /* must start with a letter */
        memmove(mod + 1, mod, i + 1);
        mod[0] = 'm';
    }
}

/* Replace the extension of `src` with `ext` into `dst`. */
static void with_ext(const char *src, const char *ext, char *dst, size_t dstlen)
{
    (void) snprintf(dst, dstlen, "%s", src);
    char *dot = strrchr(dst, '.');
    char *slash = strrchr(dst, '/');
    if (dot && (!slash || dot > slash))
        *dot = '\0';
    size_t n = strlen(dst);
    (void) snprintf(dst + n, dstlen - n, "%s", ext);
}

void com_pre_snp(wordlist *wl)
{
    char module[256], va[1200], osdi[1200], nport[1200], msg[512], *snp, *ovf;
    char *cmd;
    size_t cmdlen;
    int rc, native = 0;
    double maxerr = -1.0;               /* Enhancement-745: -1 = the default limit */
    int maxpoles = 0, order = 0;        /* Enhancement-750: 0 = the default cap / climb */

    /* optional leading flags: -osdi (default) or -native; -maxerr <x> or -force */
    while (wl && wl->wl_word && wl->wl_word[0] == '-') {
        if (eq(wl->wl_word, "-native"))    native = 1;
        else if (eq(wl->wl_word, "-osdi")) native = 0;
        else if (eq(wl->wl_word, "-force")) maxerr = 0.0;
        else if (eq(wl->wl_word, "-maxerr")) {
            char *end = NULL;
            wl = wl->wl_next;
            maxerr = (wl && wl->wl_word) ? strtod(wl->wl_word, &end) : -1.0;
            if (!wl || !wl->wl_word || end == wl->wl_word || *end || !(maxerr > 0)) {
                fprintf(cp_err, "pre_snp: -maxerr needs a positive number, the rms relative error above which "
                                "a fit is refused (default %g); -force removes the limit\n", snp2va_maxerr_default());
                return;
            }
        }
        else if (eq(wl->wl_word, "-maxpoles") || eq(wl->wl_word, "-order")) {
            const char *flag = wl->wl_word;
            char *end = NULL;
            long v;
            wl = wl->wl_next;
            v = (wl && wl->wl_word) ? strtol(wl->wl_word, &end, 10) : 0;
            if (!wl || !wl->wl_word || end == wl->wl_word || *end || v <= 0 || v > 4096) {
                fprintf(cp_err, "pre_snp: %s needs a positive pole count (the cap of the order climb, default %d, "
                                "or the pinned order)\n", flag, snp2va_maxpoles_default());
                return;
            }
            if (eq(flag, "-maxpoles")) maxpoles = (int) v; else order = (int) v;
        }
        else { fprintf(cp_err, "pre_snp: unknown option '%s'\n", wl->wl_word); return; }
        wl = wl->wl_next;
    }

    if (!wl || !wl->wl_word) {
        fprintf(cp_err, "usage: pre_snp [-osdi|-native] [-maxerr <x>|-force] [-maxpoles <N>|-order <N>] <file.sNp> [module]\n"
                        "  -osdi   (default) Touchstone -> Verilog-A -> openvaf-r -> <file>.osdi,\n"
                        "                    then load with `pre_osdi <file>.osdi`.\n"
                        "  -native           Touchstone -> <file>.nport for the built-in n-port\n"
                        "                    device (no compiler); use it in the deck with\n"
                        "                    `N1 <ports..> <ref> m` / `.model m nport(file=\"<file>.nport\")`.\n"
                        "  -maxerr <x>       accept a fit whose rms relative error is up to x (default %g);\n"
                        "  -force            accept any fit. A fit above the limit is refused, nothing written.\n"
                        "  -maxpoles <N>     the cap of the order climb (default %d poles; a fit that reaches it says so);\n"
                        "  -order <N>        pin the pole count (rounded up to a pair) instead of climbing.\n",
                snp2va_maxerr_default(), snp2va_maxpoles_default());
        return;
    }
    snp2va_set_maxerr(maxerr);
    snp2va_set_maxpoles(maxpoles);
    snp2va_set_order(order);
    snp = wl->wl_word;
    if (wl->wl_next && wl->wl_next->wl_word) {
        (void) snprintf(module, sizeof module, "%s", wl->wl_next->wl_word);
    } else {
        derive_module(snp, module, sizeof module);
    }

    /* -native: emit the compact .nport fit file; no Verilog-A / openvaf-r step. */
    if (native) {
        with_ext(snp, ".nport", nport, sizeof nport);
        rc = snp2nport_convert(snp, nport, msg, sizeof msg);
        snp2va_set_maxerr(-1.0);
        snp2va_set_maxpoles(0);
        snp2va_set_order(0);
        if (rc) {
            fprintf(cp_err, "pre_snp: %s\n", msg);
            return;
        }
        fprintf(cp_out, "pre_snp: %s -> %s  (%s)\n", snp, nport, msg);
        if (maxerr >= 0 && snp2va_last_err() > snp2va_maxerr_default())
            fprintf(cp_out, "pre_snp: accepted under %s, above the default limit of %g\n",
                    maxerr > 0 ? "-maxerr" : "-force", snp2va_maxerr_default());
        fprintf(cp_out, "pre_snp: use it with  `N1 <ports..> <ref> m`  and\n"
                        "                       `.model m nport(file=\"%s\")`\n", nport);
        return;
    }

    with_ext(snp, ".va", va, sizeof va);
    with_ext(snp, ".osdi", osdi, sizeof osdi);

    /* 1. Touchstone -> Verilog-A (the C converter) */
    rc = snp2va_convert(snp, va, module, msg, sizeof msg);
    snp2va_set_maxerr(-1.0);
    snp2va_set_maxpoles(0);
    snp2va_set_order(0);
    if (rc) {
        fprintf(cp_err, "pre_snp: %s\n", msg);
        return;
    }
    fprintf(cp_out, "pre_snp: %s -> %s  (%s, module '%s')\n", snp, va, msg, module);
    if (maxerr >= 0 && snp2va_last_err() > snp2va_maxerr_default())
        fprintf(cp_out, "pre_snp: accepted under %s, above the default limit of %g\n",
                maxerr > 0 ? "-maxerr" : "-force", snp2va_maxerr_default());

    /* 2. compile with openvaf-r -> .osdi */
    ovf = osdi_find_openvaf();
    cmdlen = strlen(ovf) + strlen(va) + strlen(osdi) + 32;
    cmd = TMALLOC(char, cmdlen);
#if defined(__MINGW32__) || defined(_MSC_VER)
    /* Enhancement-775: one extra outer pair of quotes for cmd.exe, which
       strips the first and last of a line that starts with one (see com_dl.c) */
    (void) snprintf(cmd, cmdlen, "\"\"%s\" \"%s\" -o \"%s\"\"", ovf, va, osdi);
#else
    (void) snprintf(cmd, cmdlen, "\"%s\" \"%s\" -o \"%s\"", ovf, va, osdi);
#endif
    rc = system(cmd);
    tfree(cmd);
    if (rc != 0) {
        osdi_report_compile_failure("pre_snp", rc, ovf, va);   /* Enhancement-827 */
        tfree(ovf);
        return;
    }
    tfree(ovf);
    fprintf(cp_out, "pre_snp: compiled -> %s   (load it with `pre_osdi %s`)\n", osdi, osdi);
}
