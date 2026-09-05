/**********
 * Enhancement-94: matplotlib ("pyplot") plots.
 *
 * A backend for `plotit()` that mirrors the gnuplot backend (`gnuplot.c`):
 * it writes the selected vectors to a `<file>.data` table and a `<file>.py`
 * matplotlib script, then shells out to Python. Modelled on ft_gnuplot().
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/dvec.h"
#include "ngspice/fteparse.h"
#include "pyplot.h"
#if defined(__MINGW32__) || defined(_MSC_VER)
#include <windows.h>
#include <io.h>          /* _access(): Enhancement-547 */
#else
#include <unistd.h>
#include <sys/wait.h>    /* WIFEXITED/WEXITSTATUS: Enhancement-547 */
#endif
#include <locale.h>

#define PY_MAXVECTORS 64

/* Enhancement-548: one number in the data table. `%e` carried six significant
   digits, which is what the gnuplot backend writes but not what an export
   needs: a time axis offset to 1 s with 1 ns steps collapsed to ONE distinct
   x value, and a 1 V signal with a microvolt ripple to eight distinct values.
   17 significant digits round-trip every double exactly; NaN and inf spell
   themselves, which numpy reads. */
#define PY_NUM "%.17g"

/* Enhancement-549: the data table is written in one of two formats, chosen by
   `set pyplot_export=bin|ascii` (default bin):
     bin   -- `<name>.npy`, numpy's own array file: a STRUCTURED float64 array
              with one named field per column (`time`, `v(out)`, ...; a repeated
              name gets `_2`, `_3`), so `np.load('name.npy')['v(out)']` is the
              signal and `pandas.DataFrame(np.load(...))` a table. Exact doubles,
              a fraction of the text size, loaded in milliseconds: a
              million-point, four-trace table measured 64 MB against 107 MB of
              text and 7 ms against 420 ms to load.
     ascii -- `<name>.data`, the whitespace table of old, now with a
              `# name name ...` header line naming the columns (np.loadtxt
              skips it) and 17 significant digits per number (E-548).
   Every renderer writes through this one writer; the generated script loads
   whichever was written; `pyplot -export` writes the table and nothing else. */
struct py_table {
    FILE *f;
    bool bin;
    int ncols;
};

/* `set pyplot_export=bin|ascii` -- bin (also `npy`, `binary`) unless ascii
   (also `text`, `txt`, `data`) is asked for; anything else is said and bin. */
static bool
py_export_binary(void)
{
    char fmt[BSIZE_SP];
    if (cp_getvar("pyplot_export", CP_STRING, fmt, sizeof(fmt))) {
        if (cieq(fmt, "ascii") || cieq(fmt, "text") || cieq(fmt, "txt")
            || cieq(fmt, "data"))
            return FALSE;
        if (!(cieq(fmt, "bin") || cieq(fmt, "binary") || cieq(fmt, "npy")))
            fprintf(cp_err, "Warning: pyplot_export=%s is neither 'bin' nor 'ascii'; "
                    "writing .npy\n", fmt);
    }
    return TRUE;
}

/* the data file for the format: `<name>.npy` or `<name>.data` */
static void
py_table_name(char *dst, size_t cap, const char *filename, bool bin)
{
    (void) snprintf(dst, cap, "%s.%s", filename, bin ? "npy" : "data");
}

/* append `s` to a growable string */
static void
py_str_add(char **buf, size_t *len, size_t *cap, const char *s)
{
    size_t n = strlen(s);
    if (*len + n + 1 > *cap) {
        *cap = (*len + n + 1) * 2;
        *buf = TREALLOC(char, *buf, *cap);
    }
    memcpy(*buf + *len, s, n + 1);
    *len += n;
}

/* Open the table and write its header. `names` are the column names
   (`ncols` of them); `nrows` rows of `ncols` doubles follow via py_table_row. */
static bool
py_table_open(struct py_table *t, const char *path, bool bin,
              const char *const *names, int ncols, long nrows)
{
    int i, k;
    char **uniq;

    t->f = fopen(path, bin ? "wb" : "w");
    if (!t->f) {
        perror(path);
        return FALSE;
    }
    t->bin = bin;
    t->ncols = ncols;

    /* unique column names: a repeated one (the `time` scale every trace
       shares) gets _2, _3, ... -- a structured dtype cannot repeat a field */
    uniq = TMALLOC(char *, ncols);
    for (i = 0; i < ncols; i++) {
        const char *base = (names[i] && *names[i]) ? names[i] : "col";
        char *cand = copy(base);
        for (k = 2; ; k++) {
            int j;
            for (j = 0; j < i; j++)
                if (eq(uniq[j], cand))
                    break;
            if (j == i)
                break;
            tfree(cand);
            cand = tprintf("%s_%d", base, k);
        }
        uniq[i] = cand;
    }

    if (bin) {
        /* the .npy header (format 1.0): the magic, the version, a little-endian
           u16 header length, then the dict, space-padded so that the data
           starts on a 64-byte boundary. The doubles are written as the host
           has them and the dtype says which way round they are. */
        static const unsigned short one = 1;
        const bool little = (*(const unsigned char *) &one == 1);
        unsigned char pre[10] = { 0x93, 'N', 'U', 'M', 'P', 'Y', 1, 0, 0, 0 };
        char *hdr = NULL, *tail;
        size_t hlen = 0, hcap = 0, pad, total;

        py_str_add(&hdr, &hlen, &hcap, "{'descr': [");
        for (i = 0; i < ncols; i++) {
            const char *p;
            py_str_add(&hdr, &hlen, &hcap, "('");
            for (p = uniq[i]; *p; p++) {
                char c[3] = { *p, '\0', '\0' };
                if (*p == '\\' || *p == '\'') {
                    c[0] = '\\';
                    c[1] = *p;
                }
                py_str_add(&hdr, &hlen, &hcap, c);
            }
            py_str_add(&hdr, &hlen, &hcap, little ? "', '<f8'), " : "', '>f8'), ");
        }
        tail = tprintf("], 'fortran_order': False, 'shape': (%ld,), }", nrows);
        py_str_add(&hdr, &hlen, &hcap, tail);
        tfree(tail);
        total = 10 + hlen + 1;                      /* + the closing newline */
        pad = (64 - total % 64) % 64;
        for (i = 0; i < (int) pad; i++)
            py_str_add(&hdr, &hlen, &hcap, " ");
        py_str_add(&hdr, &hlen, &hcap, "\n");
        pre[8] = (unsigned char) (hlen & 0xff);
        pre[9] = (unsigned char) ((hlen >> 8) & 0xff);
        (void) fwrite(pre, 1, sizeof pre, t->f);
        (void) fwrite(hdr, 1, hlen, t->f);
        tfree(hdr);
    } else {
        fputc('#', t->f);
        for (i = 0; i < ncols; i++)
            fprintf(t->f, " %s", uniq[i]);
        fputc('\n', t->f);
    }
    for (i = 0; i < ncols; i++)
        tfree(uniq[i]);
    tfree(uniq);
    return TRUE;
}

static void
py_table_row(struct py_table *t, const double *vals)
{
    if (t->bin) {
        (void) fwrite(vals, sizeof(double), (size_t) t->ncols, t->f);
    } else {
        int i;
        for (i = 0; i < t->ncols; i++)
            fprintf(t->f, i ? " " PY_NUM : PY_NUM, vals[i]);
        fputc('\n', t->f);
    }
}

static void
py_table_close(struct py_table *t)
{
    (void) fclose(t->f);
    t->f = NULL;
}


/* Write `s` as a single-quoted Python string literal, escaping backslashes
   and single quotes. */
static void
quote_python_string(FILE *stream, const char *s)
{
    fputc('\'', stream);
    for (; s && *s; s++) {
        if (*s == '\\' || *s == '\'')
            fputc('\\', stream);
        fputc(*s, stream);
    }
    fputc('\'', stream);
}


/* Enhancement-547: `print('pyplot: wrote <file>.<fmt>')`, the file name quoted
   as a Python literal. It used to be spliced raw, so an apostrophe in the path
   (a deck folder called `it's`) ended the string early and the whole script
   failed to parse -- after the image had been written, in fact, but with a
   traceback for a success. */
static void
emit_wrote_line(FILE *file, const char *filename, const char *fmt)
{
    fprintf(file, "print('pyplot: wrote ' + ");
    quote_python_string(file, filename);
    fprintf(file, " + '.%s')\n", fmt);
}


/* Enhancement-548: the file name part of a path, after the last separator
   (either kind, so a Windows path written with '/' is handled too). */
static const char *
path_basename(const char *path)
{
    const char *base = path, *p;
    for (p = path; *p; p++)
        if (*p == '/' || *p == '\\')
            base = p + 1;
    return base;
}


/* Enhancement-548: `os.path.join(_here, '<basename of path>')`. The script
   used to name its data table and its image relative to the directory ngspice
   ran in, so the doc's own advice -- edit the script and run it again -- failed
   from any other directory with "NAME.data not found". Now every path is
   resolved against the script's own location (`_here`, set by
   emit_data_load), which is where the data table and the image live. */
static void
emit_here_path(FILE *file, const char *path)
{
    fprintf(file, "os.path.join(_here, ");
    quote_python_string(file, path_basename(path));
    fprintf(file, ")");
}


/* Enhancement-548: `d = ...` the data table as a 2-D float array, found next
   to the script wherever the script is run from. Enhancement-549: a `.npy`
   table (a structured array, one field per column) is loaded and stacked
   into the same column layout the script indexes; a `.data` table is read
   with np.loadtxt, whose default skips the `#` header line. */
static void
emit_data_load(FILE *file, const char *filename_data, bool bin)
{
    fprintf(file, "import os\n");
    fprintf(file, "_here = os.path.dirname(os.path.abspath(__file__))\n");
    if (bin) {
        fprintf(file, "d = np.load(");
        emit_here_path(file, filename_data);
        fprintf(file, ")\n");
        fprintf(file, "d = np.stack([d[_n] for _n in d.dtype.names], axis=1)\n");
    } else {
        fprintf(file, "d = np.loadtxt(");
        emit_here_path(file, filename_data);
        fprintf(file, ")\n");
    }
}


/* Enhancement-548: `_ax.set_<axis>lim(lo, hi)` for an explicit `xlimit` /
   `ylimit`. Under `ylog` the limits used to be dropped without a word
   (`ylimit 1e-3 1 ylog` set the scale and no limits); they are applied now.
   plotit refuses a non-positive limit under a log axis before this runs
   ("Y values must be > 0 for log scale"); the check here is a backstop, since
   matplotlib cannot place such a limit either. */
static void
emit_axis_limits(FILE *file, char axis, const double *lims, bool log)
{
    if (!lims)
        return;
    if (log && (lims[0] <= 0.0 || lims[1] <= 0.0)) {
        fprintf(cp_err, "Warning: pyplot: %climit %g %g ignored under %clog: "
                "a log axis needs positive bounds.\n",
                axis, lims[0], lims[1], axis);
        return;
    }
    fprintf(file, "    _ax.set_%clim(" PY_NUM ", " PY_NUM ")\n", axis, lims[0], lims[1]);
}


/* Enhancement-551: the unit an EngFormatter may put an SI prefix on, for a
   vector type -- `500 \u00b5s`, `1 ms`, `-500 mV`, `10 kHz`, `1 k\u03a9`. A prefix on
   dB, rad, Celsius or a noise density means nothing, so those stay plain. */
static const char *
eng_unit_for(int type)
{
    switch (type) {
    case SV_TIME:        return "s";
    case SV_FREQUENCY:   return "Hz";
    case SV_VOLTAGE:     return "V";
    case SV_CURRENT:     return "A";
    case SV_POWER:       return "W";
    case SV_CAPACITANCE: return "F";
    case SV_CHARGE:      return "C";
    case SV_RES:
    case SV_IMPEDANCE:   return "\xce\xa9";          /* Ohm sign, UTF-8 */
    case SV_ADMITTANCE:  return "S";
    default:             return NULL;
    }
}


/* Enhancement-551: the default label of an axis carrying a vector type --
   `time [s]`, `voltage [V]`, `decibel [dB]` -- where a bare `s` or `V` used to
   stand. NULL for an untyped vector. The caller frees it. */
static char *
axis_label_for(int type)
{
    const char *name = ft_typenames(type);
    const char *unit = eng_unit_for(type);
    if (!name || type == SV_NOTYPE)
        return NULL;
    if (!unit)
        unit = ft_typabbrev(type);
    if (unit && *unit)
        return tprintf("%s [%s]", name, unit);
    return copy(name);
}


/* Enhancement-551: `<axis>.set_major_formatter(EngFormatter(unit='..'))` for
   a unit, nothing for none. `axis` is e.g. "    _ax.xaxis". */
static void
emit_eng_formatter(FILE *file, const char *axis, const char *unit)
{
    if (!unit)
        return;
    fprintf(file, "%s.set_major_formatter(EngFormatter(unit=", axis);
    quote_python_string(file, unit);
    fprintf(file, "))\n");
}


/* Enhancement-551: the figure title as it should read. The default title is
   the circuit's title line, which most decks begin with the comment marker
   (`* rc lowpass`); the marker and the blanks after it are dropped when the
   title IS that default, and a title the user gave on the command is kept
   verbatim. The caller frees the result. */
static char *
title_text(const char *title, const struct plot *pl)
{
    char *text = cp_unquote(title);
    if (pl && pl->pl_title && eq(title, pl->pl_title)) {
        char *p = text;
        while (*p == '*' || *p == ' ' || *p == '\t')
            p++;
        if (p != text) {
            char *stripped = copy(p);
            tfree(text);
            text = stripped;
        }
    }
    return text;
}


/* Enhancement-547: `s` as ONE argument for the shell that runs the script.
   POSIX: single-quoted, an embedded quote spelled '\''. Windows (cmd.exe):
   double-quoted -- a double quote cannot appear in a Windows path. */
static char *
shell_quote(const char *s)
{
#if defined(__MINGW32__) || defined(_MSC_VER)
    return tprintf("\"%s\"", s);
#else
    size_t n = 2;
    const char *p;
    char *out, *q;

    for (p = s; *p; p++)
        n += (*p == '\'') ? 4 : 1;
    out = TMALLOC(char, n + 1);
    q = out;
    *q++ = '\'';
    for (p = s; *p; p++) {
        if (*p == '\'') {
            memcpy(q, "'\\''", 4);
            q += 4;
        } else {
            *q++ = *p;
        }
    }
    *q++ = '\'';
    *q = '\0';
    return out;
#endif
}


/* Enhancement-547: the interpreter as the user set it. `pyplot_python` is
   spliced verbatim so that it can carry options (`/usr/bin/env python3`,
   `python3 -X utf8`) -- unless the whole value names an executable file, in
   which case it is quoted so that a path with a space (`C:\Program Files\...`)
   stays one word. */
static char *
python_arg(const char *python)
{
    if (strchr(python, ' ')) {
#if defined(_MSC_VER)
        if (_access(python, 0) == 0)
#else
        if (access(python, X_OK) == 0)
#endif
            return shell_quote(python);
    }
    return copy(python);
}


/* Enhancement-547: run the generated script and judge the outcome.
 *
 * The command line used to be built unquoted: with the deck-folder output of
 * Enhancement-183 a folder named `My Circuits` handed Python the file `My`, an
 * apostrophe left the shell waiting for a closing quote -- the script and the
 * data were written, no image was, and ngspice went on. And only a -1 from
 * system() was ever looked at: a missing interpreter or a missing matplotlib
 * printed Python's own complaint and nothing else, so a batch deck finished
 * with exit status 0 and no figure, a silent green in a CI run.
 *
 * Now the interpreter and the script path are quoted for the shell (see
 * shell_quote / python_arg), a hardcopy is waited for and a non-zero exit is
 * named together with the image that was not written, and `pyplot_status`
 * carries the status for the deck -- as `shell` publishes `shellstatus` -- so
 * `if $pyplot_status ne 0` can `quit 1`. A window runs in the background,
 * where nothing can be waited for; on POSIX the background shell names a
 * non-zero exit when it happens. */
static void
pyplot_run(const char *python, const char *filename, const char *filename_py,
           bool hardcopy, const char *fmt)
{
    char *qpy = python_arg(python);
    char *qfile = shell_quote(filename_py);
    char *cmd;
    int err, status;

#if defined(__MINGW32__) || defined(_MSC_VER)
    /* cmd.exe strips one outer pair of quotes from a command line that starts
       with a quote, so the hardcopy line is wrapped in an extra pair; `start`
       takes its first quoted argument as a window title, hence the "". */
    if (hardcopy)
        cmd = tprintf("\"%s %s\"", qpy, qfile);
    else
        cmd = tprintf("start /B \"\" %s %s", qpy, qfile);
    _flushall();
    err = system(cmd);
    status = err;                          /* the exit code, or -1 */
#else
    if (hardcopy)
        cmd = tprintf("%s %s", qpy, qfile);
    else
        cmd = tprintf("(%s %s || echo \"pyplot: the viewer exited with status $?\" >&2) &",
                      qpy, qfile);
    fflush(stdout);
    fflush(stderr);
    err = system(cmd);
    if (err == -1)
        status = -1;
    else if (WIFEXITED(err))
        status = WEXITSTATUS(err);
    else if (WIFSIGNALED(err))
        status = 128 + WTERMSIG(err);
    else
        status = err;
#endif

    if (status == -1)
        fprintf(cp_err, "Error: pyplot could not run '%s'.\n", cmd);
    else if (hardcopy && status != 0)
        fprintf(cp_err, "Error: pyplot: %s exited with status %d; %s.%s was not "
                "written (the script is %s).\n",
                python, status, filename, fmt, filename_py);
    cp_vset("pyplot_status", CP_NUM, &status);

    tfree(cmd);
    tfree(qpy);
    tfree(qfile);
}


/* Enhancement-296: emit `_ax.axhline(v)` / `_ax.axvline(v)` for each numeric value
   in a comma/space separated list (`fn` is "axhline" or "axvline"). SI suffixes are
   accepted (1k, 1meg, ...) via ngspice's own numeric parser. Non-numeric tokens are
   skipped rather than aborting the plot. */
static void
emit_reference_lines(FILE *file, const char *fn, const char *list)
{
    char *dup = copy(list);
    char *tok, *save = NULL;
    for (tok = strtok_r(dup, ", \t", &save); tok; tok = strtok_r(NULL, ", \t", &save)) {
        char *s = tok;
        double val;
        if (ft_numparse(&s, FALSE, &val) < 0)       /* SI-aware (1k, 0.5n, ...) */
            val = atof(tok);                        /* fall back; 0 for junk tokens */
        fprintf(file, "    _ax.%s(%e, color='0.5', lw=0.8, ls='--', zorder=0)\n",
                fn, val);
    }
    tfree(dup);
}


void ft_pyplot(double *xlims, double *ylims,
        double xdel, double ydel,
        const char *filename, const char *title,
        const char *xlabel, const char *ylabel,
        GRIDTYPE gridtype, PLOTTYPE plottype,
        struct dvec *vecs, int mode)
{
    const bool hist = (mode == PYMODE_HIST);
    const bool fft  = (mode == PYMODE_FFT);
    FILE *file;
    struct dvec *v;
    int i, col, numVecs, nper, nrows, row;
    bool xlog, ylog, nogrid, markers, boxes, have_style, have_figsize;
    char pointstyle[BSIZE_SP], terminal[BSIZE_SP], python[BSIZE_SP], style[BSIZE_SP];
    char figsize[BSIZE_SP], fmt[16];
    char lwarg[32];         /* Enhancement-183: "linewidth=%g, " or "" */
    double linewidth = 0.0;
    char backend[BSIZE_SP]; /* Enhancement-183: matplotlib backend override */
    bool have_backend;
    /* Enhancement-296: appearance controls. */
    char gridvar[BSIZE_SP], legendvar[BSIZE_SP];
    char axhline[BSIZE_SP], axvline[BSIZE_SP];
    bool have_grid, have_legend, have_axh, have_axv, linemarkers, transparent;
    int dpi = 100;
    /* Enhancement-183: hold a full directory path (the deck's folder) + base
       name, not just a bare "pyplot.data" -- 128 was too small for a path. */
    char filename_data[1024], filename_py[1024];
    char *text;
    double figw = 0.0, figh = 0.0;
    bool hardcopy = FALSE, bin;

    NG_IGNORE(xdel);
    NG_IGNORE(ydel);

#ifdef SHARED_MODULE
    char *llocale = setlocale(LC_NUMERIC, NULL);
    setlocale(LC_NUMERIC, "C");
#endif

    bin = py_export_binary();                     /* Enhancement-549 */
    py_table_name(filename_data, sizeof filename_data, filename, bin);
    snprintf(filename_py, sizeof(filename_py), "%s.py", filename);

    for (v = vecs, numVecs = 0; v; v = v->v_link2)
        numVecs++;

    if (numVecs == 0) {
        return;
    } else if (numVecs > PY_MAXVECTORS) {
        fprintf(cp_err, "Error: too many vectors for pyplot.\n");
        return;
    }

    /* `set pyplot_terminal=png|svg|pdf` -> render headless (Agg) to
       <file>.<fmt> rather than opening an interactive window. Enhancement-99
       adds the svg and pdf vector formats alongside png. */
    fmt[0] = '\0';
    if (cp_getvar("pyplot_terminal", CP_STRING, terminal, sizeof(terminal))) {
        if (cieq(terminal, "png") || cieq(terminal, "png/quit")) {
            strcpy(fmt, "png");
            hardcopy = TRUE;
        } else if (cieq(terminal, "svg") || cieq(terminal, "svg/quit")) {
            strcpy(fmt, "svg");
            hardcopy = TRUE;
        } else if (cieq(terminal, "pdf") || cieq(terminal, "pdf/quit")) {
            strcpy(fmt, "pdf");
            hardcopy = TRUE;
        }
    }

    /* Enhancement-99: `set pyplot_figsize=W,H` -> figure size in inches. */
    have_figsize = FALSE;
    if (cp_getvar("pyplot_figsize", CP_STRING, figsize, sizeof(figsize))) {
        if (sscanf(figsize, "%lf%*[ ,xX]%lf", &figw, &figh) == 2
                && figw > 0.0 && figh > 0.0)
            have_figsize = TRUE;
    }

    /* the Python interpreter, overridable with `set pyplot_python=...`. */
    if (!cp_getvar("pyplot_python", CP_STRING, python, sizeof(python)))
        strcpy(python, "python3");

    /* Enhancement-183: `set pyplot_backend=<name>` -> select the matplotlib
       backend explicitly (e.g. TkAgg, QtAgg, MacOSX, WebAgg, Agg). Overrides
       the automatic backend, including the 'Agg' otherwise forced for the
       png/svg/pdf terminals -- so it is the user's responsibility to pick a
       file-capable/headless backend when combining it with those. */
    have_backend = cp_getvar("pyplot_backend", CP_STRING, backend, sizeof(backend))
                   ? TRUE : FALSE;

    /* Enhancement-98: `set pyplot_subplots=N` -> stacked subplots sharing the
       x-axis, N traces per panel (0/unset = a single axis, as before). */
    if (!cp_getvar("pyplot_subplots", CP_NUM, &nper, 0))
        nper = 0;
    if (nper < 0)
        nper = 0;
    nrows = (nper > 0) ? ((numVecs + nper - 1) / nper) : 1;

    /* Enhancement-98: `set pyplot_style=<name>` -> a matplotlib style sheet
       (e.g. dark, ggplot, bmh). "dark" aliases matplotlib's dark_background. */
    have_style = cp_getvar("pyplot_style", CP_STRING, style, sizeof(style)) ? TRUE : FALSE;
    if (have_style && cieq(style, "dark"))
        strcpy(style, "dark_background");

    /* Enhancement-183: `set pyplot_linewidth=<w>` -> matplotlib line width (in
       points) applied to every trace; unset/<=0 leaves matplotlib's default. */
    lwarg[0] = '\0';
    if (cp_getvar("pyplot_linewidth", CP_REAL, &linewidth, 0) && linewidth > 0.0)
        (void) snprintf(lwarg, sizeof lwarg, "linewidth=%g, ", linewidth);

    markers = FALSE;
    if (cp_getvar("pointstyle", CP_STRING, pointstyle, sizeof(pointstyle)))
        if (cieq(pointstyle, "markers"))
            markers = TRUE;

    /* Enhancement-296: `set pyplot_markers` draws a marker at each sample ON TOP
       of the line (a cycling shape per trace), so overlaid traces are told apart
       in print or greyscale -- distinct from `pointstyle=markers`, which draws
       markers with NO line. */
    linemarkers = cp_getvar("pyplot_markers", CP_BOOL, NULL, 0);

    /* Enhancement-296: `set pyplot_grid=on|off|x|y|both` overrides the default
       (grid follows the axis type). `set pyplot_legend=off` hides the legend;
       any other value is passed as the matplotlib legend location
       (e.g. "upper right", "best"). */
    have_grid = cp_getvar("pyplot_grid", CP_STRING, gridvar, sizeof(gridvar)) ? TRUE : FALSE;
    have_legend = cp_getvar("pyplot_legend", CP_STRING, legendvar, sizeof(legendvar)) ? TRUE : FALSE;

    /* Enhancement-296: `set pyplot_axhline=v1,v2,...` / `pyplot_axvline=...` draw
       horizontal / vertical reference lines (thresholds, -3 dB, decision levels). */
    have_axh = cp_getvar("pyplot_axhline", CP_STRING, axhline, sizeof(axhline)) ? TRUE : FALSE;
    have_axv = cp_getvar("pyplot_axvline", CP_STRING, axvline, sizeof(axvline)) ? TRUE : FALSE;

    /* Enhancement-296: `set pyplot_dpi=<N>` (savefig resolution, default 100) and
       `set pyplot_transparent` (transparent figure background for a hardcopy). */
    if (!cp_getvar("pyplot_dpi", CP_NUM, &dpi, 0) || dpi < 1)
        dpi = 100;
    transparent = cp_getvar("pyplot_transparent", CP_BOOL, NULL, 0);

    /* Enhancement-299/301: `set pyplot_cursor` is the single master switch for the
       interactive cursor -- OFF by default, and the ONLY thing that turns any cursor
       on. It draws matplotlib's built-in Cursor crosshair (no extra package).
       Interactive only: it does nothing in a hardcopy, where there is no mouse (the
       window already provides pan / zoom / save-image via matplotlib's own toolbar).
       Enhancement-300/301: `set pyplot_mplcursors` only SELECTS the backend when the
       cursor is on -- the `mplcursors` package (data cursors that snap to a trace and
       show the (x, y) value on hover), with the emitted script falling back to the
       built-in Cursor if `mplcursors` is not importable where it runs. On its own,
       with `pyplot_cursor` unset, it does nothing. */
    bool mplcursors = cp_getvar("pyplot_mplcursors", CP_BOOL, NULL, 0);
    bool cursor = cp_getvar("pyplot_cursor", CP_BOOL, NULL, 0) && !hardcopy;

    boxes = (plottype == PLOT_COMB);
    if (plottype == PLOT_POINT)
        markers = TRUE;

    /* Enhancement-550: `set pyplot_decimate=auto|off|<N>`. A trace with more
       samples than the axis has pixel columns is drawn as its min/max ENVELOPE
       per column -- the same picture, since a column can only show its extremes
       -- computed in the generated script (`_envelope`). matplotlib drawing four
       million points to a 640-pixel canvas took 4.8 s of a 5.2 s run; the
       envelope draws in milliseconds. Unset or `auto`: decimate when a trace
       has more than twice the axis width in samples; `off`: every sample; a
       number: that many bins, whatever the width. Plain lines only -- a point
       plot shows its points and a step plot its steps -- and never a `vs` plot
       whose x runs backwards. An interactive window re-decimates from the full
       data on every zoom, pan and resize, so zooming in reveals the detail. */
    bool decimate = TRUE;
    int decbins = 0;
    {
        char decvar[BSIZE_SP];
        int n;
        if (cp_getvar("pyplot_decimate", CP_NUM, &n, 0)) {
            if (n < 2)
                decimate = FALSE;
            else
                decbins = n;
        } else if (cp_getvar("pyplot_decimate", CP_STRING, decvar, sizeof decvar)) {
            if (cieq(decvar, "off") || cieq(decvar, "none") || cieq(decvar, "false"))
                decimate = FALSE;
            else if (!(cieq(decvar, "on") || cieq(decvar, "auto") || cieq(decvar, "true")))
                fprintf(cp_err, "Warning: pyplot_decimate=%s is not off, auto or a bin "
                        "count; decimating automatically.\n", decvar);
        }
    }
    if (hist || fft)
        decimate = FALSE;

    /* Enhancement-551: `set pyplot_eng=off` keeps matplotlib's plain tick
       numbers (`0.0005`) instead of engineering ones (`500 \u00b5s`). */
    bool eng = TRUE;
    {
        char engvar[BSIZE_SP];
        if (cp_getvar("pyplot_eng", CP_STRING, engvar, sizeof engvar)
            && (cieq(engvar, "off") || cieq(engvar, "none") || cieq(engvar, "false")))
            eng = FALSE;
    }

    /* Enhancement-217: `pyplot -hist ...` renders each signal's VALUE distribution
       as a histogram. `set pyplot_hist_bins=<N>` sets the bin count (default the
       matplotlib 'auto' rule); `set pyplot_hist_density` normalizes to a density. */
    int histbins = 0;
    bool histdensity = FALSE;
    if (hist) {
        if (!cp_getvar("pyplot_hist_bins", CP_NUM, &histbins, 0) || histbins < 1)
            histbins = 0;                    /* 0 => matplotlib 'auto' */
        histdensity = cp_getvar("pyplot_hist_density", CP_BOOL, NULL, 0);
    }

    /* Enhancement-297: `pyplot -fft <sig> ...` plots the one-sided amplitude
       spectrum of each signal. Transient data is adaptively sampled, so the
       generated script resamples onto a UNIFORM grid (np.interp) before the FFT --
       a raw rfft over non-uniform samples would be wrong. Options:
         set pyplot_fft_window = hann|hamming|blackman|rect   (default hann)
         set pyplot_fft_db                                    (20*log10 magnitude)
         set pyplot_fft_points = <N>                          (resample length) */
    char fftwin[BSIZE_SP];
    bool fftdb = FALSE, fftlogf = FALSE;
    int fftpoints = 0;
    if (fft) {
        if (!cp_getvar("pyplot_fft_window", CP_STRING, fftwin, sizeof(fftwin)))
            strcpy(fftwin, "hann");
        fftdb = cp_getvar("pyplot_fft_db", CP_BOOL, NULL, 0);
        if (!cp_getvar("pyplot_fft_points", CP_NUM, &fftpoints, 0) || fftpoints < 8)
            fftpoints = 0;                   /* 0 => next power of two >= len */
        /* `set pyplot_fft_logf` -> log frequency axis. Set here (not via the
           command's `xlog`, which would validate the TIME scale -- including t=0 --
           and abort before the FFT runs); the DC bin is dropped so log(0) is
           never plotted. */
        fftlogf = cp_getvar("pyplot_fft_logf", CP_BOOL, NULL, 0);
    }

    switch (gridtype) {
    case GRID_LIN:
        nogrid = xlog = ylog = FALSE;
        break;
    case GRID_XLOG:
        xlog = TRUE;
        nogrid = ylog = FALSE;
        break;
    case GRID_YLOG:
        ylog = TRUE;
        nogrid = xlog = FALSE;
        break;
    case GRID_LOGLOG:
        xlog = ylog = TRUE;
        nogrid = FALSE;
        break;
    case GRID_NONE:
        nogrid = TRUE;
        xlog = ylog = FALSE;
        break;
    default:
        fprintf(cp_err, "Error: grid type unsupported by pyplot.\n");
        return;
    }

    /* Write the data table: for each row, an (x, y) pair per vector, taken
       from each vector's own scale (real part for complex data). */
    /* Row count: a line plot walks the shared scale (time/frequency). A histogram
       (Enhancement-217) only uses each signal's VALUES, and those signals may be
       raw `let` vectors whose scale length differs from their own length, so it
       walks the longest value vector instead (shorter ones pad with NaN, which the
       generated script filters out). */
    int datarows;
    if (hist) {
        datarows = 0;
        for (v = vecs; v; v = v->v_link2)
            if (v->v_length > datarows)
                datarows = v->v_length;
    } else {
        /* Enhancement-299: walk the LONGEST scale, not just the first vector's, so
           overlaying runs of different lengths (`pyplot tran1.v(out) tran2.v(out)`)
           renders every trace fully -- each vector still uses its own scale for x,
           and shorter ones pad with NaN (matplotlib skips it). For a single run all
           vectors share one scale, so this is unchanged. */
        datarows = 0;
        for (v = vecs; v; v = v->v_link2) {
            int len = (v->v_scale ? v->v_scale->v_length : v->v_length);
            if (len > datarows)
                datarows = len;
        }
    }
    {
        /* Enhancement-549: columns named after the scale and the vector. */
        const char **names = TMALLOC(const char *, 2 * numVecs);
        double *rowbuf = TMALLOC(double, 2 * numVecs);
        struct py_table tab;
        int c = 0;
        for (v = vecs; v; v = v->v_link2) {
            names[c++] = (v->v_scale && v->v_scale->v_name) ? v->v_scale->v_name : "index";
            names[c++] = v->v_name ? v->v_name : "";
        }
        if (!py_table_open(&tab, filename_data, bin, names, 2 * numVecs, datarows)) {
            tfree(names);
            tfree(rowbuf);
#ifdef SHARED_MODULE
            setlocale(LC_NUMERIC, llocale);
#endif
            return;
        }
        for (i = 0; i < datarows; i++) {
            c = 0;
            for (v = vecs; v; v = v->v_link2) {
                struct dvec *sc = v->v_scale;
                rowbuf[c++] = (sc && i < sc->v_length)
                    ? (isreal(sc) ? sc->v_realdata[i] : realpart(sc->v_compdata[i]))
                    : NAN;
                rowbuf[c++] = (i < v->v_length)
                    ? (isreal(v) ? v->v_realdata[i] : realpart(v->v_compdata[i]))
                    : NAN;
            }
            py_table_row(&tab, rowbuf);
        }
        py_table_close(&tab);
        tfree(names);
        tfree(rowbuf);
    }

    /* Enhancement-549: `pyplot -export` -- the table was the point; no script,
       no Python. */
    if (mode == PYMODE_EXPORT) {
        fprintf(cp_out, "pyplot: exported %s (%d rows, %d columns)\n",
                filename_data, datarows, 2 * numVecs);
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }

    /* Write the matplotlib script. */
    if ((file = fopen(filename_py, "w")) == NULL) {
        perror(filename);
        return;
    }
    fprintf(file, "#!/usr/bin/env python3\n");
    fprintf(file, "# generated by ngspice 'pyplot' (Enhancement-94)\n");
    fprintf(file, "import numpy as np\n");
    /* Enhancement-183: an explicit `pyplot_backend` wins; otherwise the file
       terminals render headless with Agg (unchanged). matplotlib.use() must
       precede `import matplotlib.pyplot`. */
    if (have_backend) {
        fprintf(file, "import matplotlib\n");
        fprintf(file, "matplotlib.use(");
        quote_python_string(file, backend);
        fprintf(file, ")\n");
    } else if (hardcopy) {
        fprintf(file, "import matplotlib\n");
        fprintf(file, "matplotlib.use('Agg')\n");
    }
    fprintf(file, "import matplotlib.pyplot as plt\n");
    fprintf(file, "from matplotlib.ticker import EngFormatter\n");
    /* Enhancement-98: apply a matplotlib style sheet if requested (ignore an
       unknown name rather than aborting the plot). */
    if (have_style) {
        fprintf(file, "try:\n    plt.style.use(");
        quote_python_string(file, style);
        fprintf(file, ")\nexcept Exception:\n    pass\n");
    }
    emit_data_load(file, filename_data, bin);
    fprintf(file, "if d.ndim == 1:\n    d = d.reshape(-1, %d)\n", 2 * numVecs);
    /* Enhancement-98: one axis, or `nrows` stacked subplots sharing the x-axis.
       `axes` is always a 2-D array (squeeze=False) so it is indexed uniformly. */
    /* Histograms of different signals have unrelated value ranges, so their panels
       must NOT share an x-axis (a line plot's panels share the time/frequency axis). */
    const char *sharex = hist ? "False" : "True";
    if (have_figsize)
        fprintf(file,
                "fig, axes = plt.subplots(%d, 1, sharex=%s, squeeze=False, "
                "figsize=(%g, %g))\n", nrows, sharex, figw, figh);
    else
        fprintf(file, "fig, axes = plt.subplots(%d, 1, sharex=%s, squeeze=False)\n",
                nrows, sharex);

    /* Enhancement-550: the envelope machinery (see `decimate` above). */
    if (decimate) {
        fprintf(file, "def _envelope(x, y, npix):\n");
        fprintf(file, "    n = x.size\n");
        fprintf(file, "    if npix < 2 or n <= 2 * npix or np.any(np.diff(x) < 0):\n");
        fprintf(file, "        return x, y\n");
        fprintf(file, "    edges = np.linspace(x[0], x[-1], npix + 1)\n");
        fprintf(file, "    cuts = np.searchsorted(x, edges[1:-1])\n");
        fprintf(file, "    starts = np.concatenate(([0], cuts)); ends = np.concatenate((cuts, [n]))\n");
        fprintf(file, "    keep = []\n");
        fprintf(file, "    for a, b in zip(starts, ends):\n");
        fprintf(file, "        if b > a:\n");
        fprintf(file, "            seg = y[a:b]\n");
        fprintf(file, "            i = a + int(seg.argmin()); j = a + int(seg.argmax())\n");
        fprintf(file, "            keep.append(min(i, j)); keep.append(max(i, j))\n");
        fprintf(file, "    k = np.array(keep)\n");
        fprintf(file, "    return x[k], y[k]\n");
        fprintf(file, "_ndec = [0, 0]\n");
        fprintf(file, "def _dec(x, y, npix):\n");
        fprintf(file, "    m = ~np.isnan(x) & ~np.isnan(y)\n");
        fprintf(file, "    x = x[m]; y = y[m]\n");
        fprintf(file, "    xs, ys = _envelope(x, y, npix)\n");
        fprintf(file, "    if xs.size < x.size:\n");
        fprintf(file, "        _ndec[0] = max(_ndec[0], int(x.size)); _ndec[1] = int(xs.size)\n");
        fprintf(file, "    return xs, ys, x, y\n");
        if (decbins > 0)
            fprintf(file, "_npix0 = %d\n", decbins);
        else if (hardcopy)
            fprintf(file, "_npix0 = max(2, int(fig.get_figwidth() * %d))\n", dpi);
        else
            fprintf(file, "_npix0 = max(2, int(fig.get_figwidth() * fig.dpi))\n");
        if (!hardcopy) {
            fprintf(file, "_full = {}\n");
            fprintf(file, "def _reg(ln, x, y):\n");
            fprintf(file, "    _full[ln] = (x, y)\n");
            fprintf(file, "def _redec(ax):\n");
            fprintf(file, "    lo, hi = ax.get_xlim()\n");
            if (decbins > 0)
                fprintf(file, "    npix = %d\n", decbins);
            else
                fprintf(file, "    npix = max(2, int(ax.bbox.width))\n");
            fprintf(file, "    for ln, (x, y) in _full.items():\n");
            fprintf(file, "        if ln.axes is not ax:\n");
            fprintf(file, "            continue\n");
            fprintf(file, "        a = max(0, int(np.searchsorted(x, lo)) - 1)\n");
            fprintf(file, "        b = min(x.size, int(np.searchsorted(x, hi, side='right')) + 1)\n");
            fprintf(file, "        xs, ys = _envelope(x[a:b], y[a:b], npix)\n");
            fprintf(file, "        ln.set_data(xs, ys)\n");
        }
    }

    /* Enhancement-297: the FFT window (numpy) chosen by pyplot_fft_window. */
    const char *winexpr = "np.hanning(_N)";
    if (fft) {
        if (cieq(fftwin, "hamming"))       winexpr = "np.hamming(_N)";
        else if (cieq(fftwin, "blackman")) winexpr = "np.blackman(_N)";
        else if (cieq(fftwin, "rect") || cieq(fftwin, "none")
                 || cieq(fftwin, "boxcar")) winexpr = "np.ones(_N)";
    }

    /* Enhancement-548: traces of DIFFERENT types (a voltage and a current,
       `pyplot v(out) i(v1)`) used to share one axis with no label at all --
       plotit hands over no `ylabel` for a mixed list -- so the milliamp trace
       lay flat along the bottom of the volt scale. Stock `plot` gives each type
       its own scale; so does this now: within a panel, the first trace's type
       owns the left axis and any other type goes to a `twinx()` axis on the
       right, each labelled with its type, the legend combined, and every trace
       given an explicit colour (a twin axis restarts matplotlib's colour cycle,
       so the two first traces would both have come out blue). Explicit
       `ylimit`, `ylog` and the reference lines apply to the left axis. */
    bool mixed = FALSE;
    if (!hist && !fft)
        for (v = vecs->v_link2; v; v = v->v_link2)
            if (v->v_type != vecs->v_type)
                mixed = TRUE;
    int row_type[PY_MAXVECTORS];        /* the type owning each panel's left axis */
    int twin_type[PY_MAXVECTORS];       /* the type on the panel's twin axis, if any */
    for (i = 0; i < PY_MAXVECTORS; i++) {
        row_type[i] = SV_NOTYPE;
        twin_type[i] = SV_NOTYPE;
    }
    if (mixed) {
        fprintf(file, "_tw = {}\n");
        fprintf(file, "def _twin(_r):\n");
        fprintf(file, "    if _r not in _tw:\n");
        fprintf(file, "        _tw[_r] = axes[_r, 0].twinx()\n");
        fprintf(file, "    return _tw[_r]\n");
    }

    col = 0;
    row = 0;
    i = 0;
    for (v = vecs; v; v = v->v_link2) {
        row = (nper > 0) ? (i / nper) : 0;
        if (fft) {
            /* Resample the (possibly non-uniform) time series onto a uniform grid,
               window it, and take the one-sided amplitude spectrum. Scaling by
               2/sum(w) makes a pure tone read back its amplitude. */
            fprintf(file, "_t = d[:, %d]; _y = d[:, %d]\n", col, col + 1);
            fprintf(file, "_m = ~np.isnan(_t) & ~np.isnan(_y); _t = _t[_m]; _y = _y[_m]\n");
            fprintf(file, "if _t.size >= 2:\n");
            if (fftpoints > 0)
                fprintf(file, "    _N = %d\n", fftpoints);
            else
                fprintf(file, "    _N = 1 << int(np.ceil(np.log2(max(8, _t.size))))\n");
            fprintf(file, "    _tu = np.linspace(_t[0], _t[-1], _N)\n");
            fprintf(file, "    _yu = np.interp(_tu, _t, _y)\n");
            fprintf(file, "    _w = %s\n", winexpr);
            fprintf(file, "    _dt = (_t[-1] - _t[0]) / (_N - 1)\n");
            fprintf(file, "    _Y = np.fft.rfft((_yu - _yu.mean()) * _w)\n");
            fprintf(file, "    _f = np.fft.rfftfreq(_N, _dt)\n");
            fprintf(file, "    _mag = np.abs(_Y) * 2.0 / np.sum(_w)\n");
            /* Enhancement-297: drop the DC bin under a log frequency axis. */
            if (fftlogf)
                fprintf(file, "    _f = _f[1:]; _mag = _mag[1:]\n");
            fprintf(file, "    axes[%d, 0].plot(_f, %s, %slabel=", row,
                    fftdb ? "20.0 * np.log10(np.maximum(_mag, 1e-30))" : "_mag",
                    lwarg);
            quote_python_string(file, v->v_name ? v->v_name : "");
            fprintf(file, ")\n");
            col += 2;
            i++;
            continue;
        }
        /* Enhancement-548: the axis this trace is drawn on (see `mixed`). */
        char axexpr[32];
        if (row_type[row] == SV_NOTYPE)
            row_type[row] = (int) v->v_type;
        if (mixed && (int) v->v_type != row_type[row]) {
            if (twin_type[row] == SV_NOTYPE)
                twin_type[row] = (int) v->v_type;
            (void) snprintf(axexpr, sizeof axexpr, "_twin(%d)", row);
        } else
            (void) snprintf(axexpr, sizeof axexpr, "axes[%d, 0]", row);
        if (hist) {
            /* Enhancement-217: the VALUE column (col+1), NaN-filtered so vectors
               of unequal length (padded with NaN in the data table) histogram
               cleanly. Overlaid histograms on one axis get alpha transparency. */
            fprintf(file, "%s.hist(d[:, %d][~np.isnan(d[:, %d])], ", axexpr, col + 1, col + 1);
            if (histbins > 0)
                fprintf(file, "bins=%d, ", histbins);
            else
                fprintf(file, "bins='auto', ");
            if (histdensity)
                fprintf(file, "density=True, ");
            /* Transparency only when more than one histogram shares a panel
               (signals-per-panel = nper, or all numVecs on a single axis). */
            if (((nper > 0) ? nper : numVecs) > 1)
                fprintf(file, "alpha=0.6, ");    /* overlaid: see through */
        } else {
            /* Enhancement-550: the trace's samples -- its envelope, when there
               are more than the axis can show and it is a plain line; the full
               data is kept beside a window's line so a zoom can re-decimate. */
            const bool dec_this = decimate && !markers && !boxes;
            if (dec_this)
                fprintf(file, "_x, _y, _fx, _fy = _dec(d[:, %d], d[:, %d], _npix0)\n",
                        col, col + 1);
            else
                fprintf(file, "_x, _y = d[:, %d], d[:, %d]\n", col, col + 1);
            fprintf(file, "_ln, = %s.", axexpr);
            if (boxes)
                fprintf(file, "step(_x, _y, where='mid', %s", lwarg);
            else if (markers)
                fprintf(file, "plot(_x, _y, marker='.', linestyle='None', ");
            else if (linemarkers) {
                /* Enhancement-296: line + a cycling marker shape, so overlaid traces
                   are distinguishable without colour. */
                static const char *mk[] = { "o", "s", "^", "D", "v", "*", "P", "X" };
                fprintf(file, "plot(_x, _y, marker='%s', markevery=0.1, %s",
                        mk[i % 8], lwarg);
            } else
                fprintf(file, "plot(_x, _y, %s", lwarg);
            if (mixed)
                fprintf(file, "color='C%d', ", i % 10);
            fprintf(file, "label=");
            quote_python_string(file, v->v_name ? v->v_name : "");
            fprintf(file, ")\n");
            if (dec_this && !hardcopy)
                fprintf(file, "_reg(_ln, _fx, _fy)\n");
            col += 2;
            i++;
            continue;
        }
        fprintf(file, "label=");
        quote_python_string(file, v->v_name ? v->v_name : "");
        fprintf(file, ")\n");
        col += 2;
        i++;
    }

    /* Enhancement-550: say when a trace was drawn as its envelope, and hook a
       window's zoom, pan and resize to re-decimate from the full data. */
    if (decimate) {
        fprintf(file, "if _ndec[0]:\n");
        fprintf(file, "    print('pyplot: %%d samples per trace drawn as a %%d-point envelope "
                      "(set pyplot_decimate=off for every sample)' %% (_ndec[0], _ndec[1]))\n");
        if (!hardcopy) {
            fprintf(file, "for _a in fig.axes:\n");
            fprintf(file, "    _a.callbacks.connect('xlim_changed', _redec)\n");
            fprintf(file, "fig.canvas.mpl_connect('resize_event', "
                          "lambda _e: [_redec(_a) for _a in fig.axes])\n");
        }
    }

    /* Per-axis cosmetics applied to every panel; the x-label goes on the
       bottom panel only, the title becomes the figure suptitle. */
    /* Enhancement-551: the types behind the two axes -- the scale's for x, the
       (single) value type for y -- give the tick units and the default labels.
       A label plotit passed is the bare unit abbreviation unless the user gave
       one; the abbreviation is replaced by `time [s]` / `voltage [V]`, the
       user's text is kept. */
    const int xtype = vecs->v_scale ? (int) vecs->v_scale->v_type : SV_NOTYPE;
    const int ytype = mixed ? SV_NOTYPE : (int) vecs->v_type;
    const char *xunit = eng && !hist && !fft ? eng_unit_for(xtype) : NULL;
    const char *yunit = eng && !hist && !fft ? eng_unit_for(ytype) : NULL;
    const char *vunit = eng ? eng_unit_for((int) vecs->v_type) : NULL;   /* the value's */
    char *xdefault = axis_label_for(xtype);
    char *ydefault = axis_label_for((int) vecs->v_type);
    const char *xabbrev = ft_typabbrev(xtype);
    const char *yabbrev = ft_typabbrev((int) vecs->v_type);
    const bool xlabel_is_default = xlabel && xabbrev && eq(xlabel, xabbrev);
    const bool ylabel_is_default = ylabel && yabbrev && eq(ylabel, yabbrev);

    fprintf(file, "for _ax in axes[:, 0]:\n");
    /* Enhancement-217: for a histogram the y-axis is the count (or density); for a
       line plot it is the signal type passed in as `ylabel`. */
    if (fft) {
        if (fftdb || !vunit)
            fprintf(file, "    _ax.set_ylabel('%s')\n",
                    fftdb ? "Magnitude [dB]" : "Magnitude");
        else
            fprintf(file, "    _ax.set_ylabel('Magnitude [%s]')\n", vunit);
    } else if (hist) {
        fprintf(file, "    _ax.set_ylabel('%s')\n", histdensity ? "density" : "count");
    } else if (ylabel) {
        text = (ylabel_is_default && ydefault) ? copy(ydefault) : cp_unquote(ylabel);
        fprintf(file, "    _ax.set_ylabel(");
        quote_python_string(file, text);
        fprintf(file, ")\n");
        tfree(text);
    }
    if (xlog || (fft && fftlogf))
        fprintf(file, "    _ax.set_xscale('log')\n");
    if (ylog)
        fprintf(file, "    _ax.set_yscale('log')\n");
    /* Enhancement-551: the tick formatters go AFTER the scale -- set_xscale('log')
       installs matplotlib's own log formatter and would undo them. */
    emit_eng_formatter(file, "    _ax.xaxis",
                       fft ? (eng ? "Hz" : NULL) : hist ? vunit : xunit);
    emit_eng_formatter(file, "    _ax.yaxis",
                       fft ? ((fftdb || !vunit) ? NULL : vunit) : hist ? NULL : yunit);
    /* Enhancement-296: `pyplot_grid` overrides the default (grid follows axis type). */
    if (have_grid) {
        if (cieq(gridvar, "off") || cieq(gridvar, "none") || cieq(gridvar, "false"))
            fprintf(file, "    _ax.grid(False)\n");
        else if (cieq(gridvar, "x"))
            fprintf(file, "    _ax.grid(True, which='both', axis='x')\n");
        else if (cieq(gridvar, "y"))
            fprintf(file, "    _ax.grid(True, which='both', axis='y')\n");
        else
            fprintf(file, "    _ax.grid(True, which='both')\n");
    } else if (!nogrid)
        fprintf(file, "    _ax.grid(True, which='both')\n");
    /* Enhancement-296: horizontal / vertical reference lines. */
    if (have_axh)
        emit_reference_lines(file, "axhline", axhline);
    if (have_axv)
        emit_reference_lines(file, "axvline", axvline);
    /* Enhancement-182: xlims/ylims arrive non-NULL only when the user gave
     * explicit `xlimit`/`ylimit` on the command; otherwise the axes are left
     * to matplotlib's autoscaling (with fig.tight_layout() below). */
    emit_axis_limits(file, 'x', xlims, xlog);
    emit_axis_limits(file, 'y', ylims, ylog);
    /* Enhancement-296: `pyplot_legend=off` hides the legend; any other value is
       the matplotlib legend location. Unset -> the default `legend()`. */
    if (have_legend) {
        if (cieq(legendvar, "off") || cieq(legendvar, "none") || cieq(legendvar, "false"))
            ;                                        /* no legend */
        else {
            /* matplotlib locations contain a space ("upper right"), but `set`
               keeps only the first word, so accept an underscore form
               (`upper_right`) and convert it back to a space here. */
            char *p;
            for (p = legendvar; *p; p++)
                if (*p == '_')
                    *p = ' ';
            fprintf(file, "    _ax.legend(loc=");
            quote_python_string(file, legendvar);
            fprintf(file, ")\n");
        }
    } else
        fprintf(file, "    _ax.legend()\n");
    /* Enhancement-548: a mixed plot labels each panel's left axis with the type
       that owns it and the twin with its own, and combines the two legends. */
    if (mixed) {
        int r;
        for (r = 0; r < nrows; r++) {
            char *left = axis_label_for(row_type[r]);
            char *right = axis_label_for(twin_type[r]);
            char axis[48];
            if (left) {
                fprintf(file, "axes[%d, 0].set_ylabel(", r);
                quote_python_string(file, left);
                fprintf(file, ")\n");
                tfree(left);
            }
            (void) snprintf(axis, sizeof axis, "axes[%d, 0].yaxis", r);
            emit_eng_formatter(file, axis, eng ? eng_unit_for(row_type[r]) : NULL);
            if (twin_type[r] != SV_NOTYPE) {
                if (right) {
                    fprintf(file, "_twin(%d).set_ylabel(", r);
                    quote_python_string(file, right);
                    fprintf(file, ")\n");
                }
                (void) snprintf(axis, sizeof axis, "_twin(%d).yaxis", r);
                emit_eng_formatter(file, axis, eng ? eng_unit_for(twin_type[r]) : NULL);
            }
            if (right)
                tfree(right);
        }
        if (!(have_legend && (cieq(legendvar, "off") || cieq(legendvar, "none")
                              || cieq(legendvar, "false")))) {
            fprintf(file, "for _r, _t in _tw.items():\n");
            fprintf(file, "    _h1, _l1 = axes[_r, 0].get_legend_handles_labels()\n");
            fprintf(file, "    _h2, _l2 = _t.get_legend_handles_labels()\n");
            fprintf(file, "    axes[_r, 0].legend(_h1 + _h2, _l1 + _l2");
            if (have_legend) {
                fprintf(file, ", loc=");
                quote_python_string(file, legendvar);
            }
            fprintf(file, ")\n");
        }
    }
    /* Enhancement-217: a histogram's x-axis is the signal VALUE (the `ylabel` type),
       and the panels do not share it, so it is labelled on every panel; a line
       plot's shared time/frequency axis is labelled on the bottom panel only. */
    if (fft) {
        fprintf(file, "axes[-1, 0].set_xlabel('Frequency [Hz]')\n");
    } else {
        if (hist && ylabel) {
            text = (ylabel_is_default && ydefault) ? copy(ydefault) : cp_unquote(ylabel);
            fprintf(file, "    _ax.set_xlabel(");
            quote_python_string(file, text);
            fprintf(file, ")\n");
            tfree(text);
        }
        if (!hist && xlabel) {
            text = (xlabel_is_default && xdefault) ? copy(xdefault) : cp_unquote(xlabel);
            fprintf(file, "axes[-1, 0].set_xlabel(");
            quote_python_string(file, text);
            fprintf(file, ")\n");
            tfree(text);
        }
    }
    if (xdefault)
        tfree(xdefault);
    if (ydefault)
        tfree(ydefault);
    if (title) {
        text = title_text(title, vecs->v_plot);
        fprintf(file, "fig.suptitle(");
        quote_python_string(file, text);
        fprintf(file, ")\n");
        tfree(text);
    }
    fprintf(file, "fig.tight_layout()\n");
    if (hardcopy) {
        /* Enhancement-296: `pyplot_dpi` (default 100) and `pyplot_transparent`. */
        fprintf(file, "fig.savefig(");
        emit_here_path(file, filename);
        fprintf(file, " + '.%s', dpi=%d%s)\n", fmt, dpi,
                transparent ? ", transparent=True" : "");
        emit_wrote_line(file, filename, fmt);
    } else {
        /* Enhancement-299/300: an interactive cursor, kept in a variable so it is
           not garbage-collected before the event loop runs. `pyplot_mplcursors`
           uses the `mplcursors` package (value readouts that snap to a trace on
           hover) and degrades to the built-in `matplotlib.widgets.Cursor` crosshair
           if it is not importable where the script runs; otherwise the crosshair is
           emitted directly (core matplotlib, no extra package). */
        if (cursor && mplcursors) {
            fprintf(file, "try:\n");
            fprintf(file, "    import mplcursors\n");
            fprintf(file, "    _mpl = mplcursors.cursor(hover=True)\n");
            fprintf(file, "except Exception:\n");
            fprintf(file, "    from matplotlib.widgets import Cursor\n");
            fprintf(file, "    _curs = [Cursor(_a, useblit=True, color='0.5', "
                          "linewidth=0.8) for _a in axes[:, 0]]\n");
        } else if (cursor) {
            fprintf(file, "from matplotlib.widgets import Cursor\n");
            fprintf(file, "_curs = [Cursor(_a, useblit=True, color='0.5', linewidth=0.8) "
                          "for _a in axes[:, 0]]\n");
        }
        fprintf(file, "plt.show()\n");
    }
    (void) fclose(file);

    pyplot_run(python, filename, filename_py, hardcopy, fmt);

#ifdef SHARED_MODULE
    setlocale(LC_NUMERIC, llocale);
#endif
}


/* Enhancement-218: `pyplot -contour <z> <x> <y>`. A 2-D parameter sweep leaves a
   quantity z sampled over a grid of two swept knobs; the natural view is a filled
   contour map of z across the (x, y) plane. `vecs` is the 3-vector list built by
   plotit -- z first, then x, then y (each the flattened grid, all one length). We
   triangulate the (x, y) points (matplotlib tricontourf), so gridded OR scattered
   sweep data plots with no dimension metadata. Same pyplot_* settings as ft_pyplot. */
void
ft_pyplot_contour(const char *filename, const char *title, struct dvec *vecs)
{
    FILE *file;
    struct dvec *z, *x, *y;
    int i, n, numVecs;
    bool hardcopy = FALSE, bin, have_style, have_figsize, have_backend, lines;
    int levels;
    char terminal[BSIZE_SP], python[BSIZE_SP], style[BSIZE_SP];
    char figsize[BSIZE_SP], backend[BSIZE_SP], cmap[BSIZE_SP], fmt[16];
    char filename_data[1024], filename_py[1024];
    double figw = 0.0, figh = 0.0;

#ifdef SHARED_MODULE
    char *llocale = setlocale(LC_NUMERIC, NULL);
    setlocale(LC_NUMERIC, "C");
#endif

    /* need exactly three vectors: z (the contoured quantity), x and y (the axes). */
    for (z = vecs, numVecs = 0; z; z = z->v_link2)
        numVecs++;
    if (numVecs != 3) {
        fprintf(cp_err, "Error: pyplot -contour needs exactly three vectors: "
                        "<z> <x> <y> (got %d).\n", numVecs);
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }
    z = vecs;
    x = vecs->v_link2;
    y = vecs->v_link2->v_link2;

    /* the flattened grid: all three vectors share a length; take the shortest to
       stay in bounds if a sweep produced a ragged tail. */
    n = z->v_length;
    if (x->v_length < n) n = x->v_length;
    if (y->v_length < n) n = y->v_length;
    if (n < 3) {
        fprintf(cp_err, "Error: pyplot -contour needs at least three sample "
                        "points to triangulate (got %d).\n", n);
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }

    /* same terminal / interpreter / backend / style / figsize handling as ft_pyplot */
    fmt[0] = '\0';
    if (cp_getvar("pyplot_terminal", CP_STRING, terminal, sizeof(terminal))) {
        if (cieq(terminal, "png") || cieq(terminal, "png/quit")) {
            strcpy(fmt, "png"); hardcopy = TRUE;
        } else if (cieq(terminal, "svg") || cieq(terminal, "svg/quit")) {
            strcpy(fmt, "svg"); hardcopy = TRUE;
        } else if (cieq(terminal, "pdf") || cieq(terminal, "pdf/quit")) {
            strcpy(fmt, "pdf"); hardcopy = TRUE;
        }
    }
    if (!cp_getvar("pyplot_python", CP_STRING, python, sizeof(python)))
        strcpy(python, "python3");
    have_backend = cp_getvar("pyplot_backend", CP_STRING, backend, sizeof(backend))
                   ? TRUE : FALSE;
    have_figsize = FALSE;
    if (cp_getvar("pyplot_figsize", CP_STRING, figsize, sizeof(figsize))) {
        if (sscanf(figsize, "%lf%*[ ,xX]%lf", &figw, &figh) == 2
                && figw > 0.0 && figh > 0.0)
            have_figsize = TRUE;
    }
    have_style = cp_getvar("pyplot_style", CP_STRING, style, sizeof(style)) ? TRUE : FALSE;
    if (have_style && cieq(style, "dark"))
        strcpy(style, "dark_background");

    /* contour-specific knobs: number of levels (0 => matplotlib auto), an overlaid
       labelled line set, and the colormap. */
    if (!cp_getvar("pyplot_contour_levels", CP_NUM, &levels, 0) || levels < 1)
        levels = 0;
    lines = cp_getvar("pyplot_contour_lines", CP_BOOL, NULL, 0);
    if (!cp_getvar("pyplot_contour_cmap", CP_STRING, cmap, sizeof(cmap)))
        strcpy(cmap, "viridis");

    bin = py_export_binary();                     /* Enhancement-549 */
    py_table_name(filename_data, sizeof filename_data, filename, bin);
    snprintf(filename_py, sizeof(filename_py), "%s.py", filename);

    /* data table: one (x, y, z) triple per row (real part for complex data). */
    {
        const char *names[3] = { x->v_name ? x->v_name : "x",
                                 y->v_name ? y->v_name : "y",
                                 z->v_name ? z->v_name : "z" };
        struct py_table tab;
        if (!py_table_open(&tab, filename_data, bin, names, 3, n)) {
#ifdef SHARED_MODULE
            setlocale(LC_NUMERIC, llocale);
#endif
            return;
        }
        for (i = 0; i < n; i++) {
            double row[3];
            row[0] = isreal(x) ? x->v_realdata[i] : realpart(x->v_compdata[i]);
            row[1] = isreal(y) ? y->v_realdata[i] : realpart(y->v_compdata[i]);
            row[2] = isreal(z) ? z->v_realdata[i] : realpart(z->v_compdata[i]);
            py_table_row(&tab, row);
        }
        py_table_close(&tab);
    }

    /* matplotlib script: a triangulated filled contour with a colorbar. */
    if ((file = fopen(filename_py, "w")) == NULL) {
        perror(filename);
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }
    fprintf(file, "#!/usr/bin/env python3\n");
    fprintf(file, "# generated by ngspice 'pyplot -contour' (Enhancement-218)\n");
    fprintf(file, "import numpy as np\n");
    if (have_backend) {
        fprintf(file, "import matplotlib\nmatplotlib.use(");
        quote_python_string(file, backend);
        fprintf(file, ")\n");
    } else if (hardcopy) {
        fprintf(file, "import matplotlib\nmatplotlib.use('Agg')\n");
    }
    fprintf(file, "import matplotlib.pyplot as plt\n");
    if (have_style) {
        fprintf(file, "try:\n    plt.style.use(");
        quote_python_string(file, style);
        fprintf(file, ")\nexcept Exception:\n    pass\n");
    }
    emit_data_load(file, filename_data, bin);
    fprintf(file, "if d.ndim == 1:\n    d = d.reshape(-1, 3)\n");
    fprintf(file, "x = d[:, 0]; y = d[:, 1]; z = d[:, 2]\n");
    if (have_figsize)
        fprintf(file, "fig, ax = plt.subplots(figsize=(%g, %g))\n", figw, figh);
    else
        fprintf(file, "fig, ax = plt.subplots(figsize=(7.0, 5.4))\n");
    if (levels > 0)
        fprintf(file, "levels = %d\n", levels);
    else
        fprintf(file, "levels = None\n");
    /* triangulation fails on collinear/degenerate input (a 1-D sweep): say so
       rather than dying with a bare matplotlib traceback. */
    fprintf(file, "try:\n");
    fprintf(file, "    cf = ax.tricontourf(x, y, z, levels=levels, cmap=");
    quote_python_string(file, cmap);
    fprintf(file, ")\n");
    if (lines) {
        fprintf(file, "    cl = ax.tricontour(x, y, z, levels=cf.levels, "
                      "colors='k', linewidths=0.5, alpha=0.6)\n");
        fprintf(file, "    ax.clabel(cl, inline=True, fontsize=8, fmt='%%.3g')\n");
    }
    fprintf(file, "except (RuntimeError, ValueError) as e:\n");
    fprintf(file, "    raise SystemExit('pyplot -contour: cannot triangulate the "
                  "(x, y) points -- a contour needs a genuine 2-D sweep '\n"
                  "                     '(the points must not be collinear): ' + str(e))\n");
    fprintf(file, "cb = fig.colorbar(cf, ax=ax, pad=0.02)\n");
    fprintf(file, "cb.set_label(");
    quote_python_string(file, z->v_name ? z->v_name : "z");
    fprintf(file, ")\n");
    /* Enhancement-551: engineering ticks wherever an axis carries an SI unit */
    fprintf(file, "from matplotlib.ticker import EngFormatter\n");
    emit_eng_formatter(file, "ax.xaxis", eng_unit_for((int) x->v_type));
    emit_eng_formatter(file, "ax.yaxis", eng_unit_for((int) y->v_type));
    if (eng_unit_for((int) z->v_type)) {
        fprintf(file, "cb.formatter = EngFormatter(unit=");
        quote_python_string(file, eng_unit_for((int) z->v_type));
        fprintf(file, "); cb.update_ticks()\n");
    }
    fprintf(file, "ax.set_xlabel(");
    quote_python_string(file, x->v_name ? x->v_name : "x");
    fprintf(file, ")\n");
    fprintf(file, "ax.set_ylabel(");
    quote_python_string(file, y->v_name ? y->v_name : "y");
    fprintf(file, ")\n");
    if (title) {
        char *text = title_text(title, vecs->v_plot);
        fprintf(file, "ax.set_title(");
        quote_python_string(file, text);
        fprintf(file, ")\n");
        tfree(text);
    }
    fprintf(file, "fig.tight_layout()\n");
    if (hardcopy) {
        fprintf(file, "fig.savefig(");
        emit_here_path(file, filename);
        fprintf(file, " + '.%s', dpi=110)\n", fmt);
        emit_wrote_line(file, filename, fmt);
    } else {
        fprintf(file, "plt.show()\n");
    }
    (void) fclose(file);

    pyplot_run(python, filename, filename_py, hardcopy, fmt);

#ifdef SHARED_MODULE
    setlocale(LC_NUMERIC, llocale);
#endif
}


/* Enhancement-254: `pyplot -smith <complex vectors>` -- plot reflection
   coefficients (S11, S22, Gamma, stability/gain-circle traces, ...) on a Smith
   chart. Each vector is drawn as a curve in the reflection-coefficient plane
   (real part = x, imaginary part = y) over the standard Smith grid (the unit
   circle |Gamma| = 1, the constant-resistance circles and the constant-reactance
   arcs). Reuses the same pyplot_* settings as ft_pyplot (terminal, python,
   backend, style, figsize). */
void
ft_pyplot_smith(const char *filename, const char *title, struct dvec *vecs)
{
    FILE *file;
    struct dvec *d;
    int i, vi, numVecs;
    bool hardcopy = FALSE, bin, have_style, have_figsize, have_backend;
    char terminal[BSIZE_SP], python[BSIZE_SP], style[BSIZE_SP];
    char figsize[BSIZE_SP], backend[BSIZE_SP], fmt[16];
    char filename_data[1024], filename_py[1024];
    double figw = 0.0, figh = 0.0;

#ifdef SHARED_MODULE
    char *llocale = setlocale(LC_NUMERIC, NULL);
    setlocale(LC_NUMERIC, "C");
#endif

    for (d = vecs, numVecs = 0; d; d = d->v_link2)
        numVecs++;
    if (numVecs < 1) {
        fprintf(cp_err, "Error: pyplot -smith needs at least one vector.\n");
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }

    /* same terminal / interpreter / backend / style / figsize handling as ft_pyplot */
    fmt[0] = '\0';
    if (cp_getvar("pyplot_terminal", CP_STRING, terminal, sizeof(terminal))) {
        if (cieq(terminal, "png") || cieq(terminal, "png/quit")) {
            strcpy(fmt, "png"); hardcopy = TRUE;
        } else if (cieq(terminal, "svg") || cieq(terminal, "svg/quit")) {
            strcpy(fmt, "svg"); hardcopy = TRUE;
        } else if (cieq(terminal, "pdf") || cieq(terminal, "pdf/quit")) {
            strcpy(fmt, "pdf"); hardcopy = TRUE;
        }
    }
    if (!cp_getvar("pyplot_python", CP_STRING, python, sizeof(python)))
        strcpy(python, "python3");
    have_backend = cp_getvar("pyplot_backend", CP_STRING, backend, sizeof(backend))
                   ? TRUE : FALSE;
    have_figsize = FALSE;
    if (cp_getvar("pyplot_figsize", CP_STRING, figsize, sizeof(figsize))) {
        if (sscanf(figsize, "%lf%*[ ,xX]%lf", &figw, &figh) == 2
                && figw > 0.0 && figh > 0.0)
            have_figsize = TRUE;
    }
    have_style = cp_getvar("pyplot_style", CP_STRING, style, sizeof(style)) ? TRUE : FALSE;
    if (have_style && cieq(style, "dark"))
        strcpy(style, "dark_background");

    bin = py_export_binary();                     /* Enhancement-549 */
    py_table_name(filename_data, sizeof filename_data, filename, bin);
    snprintf(filename_py, sizeof(filename_py), "%s.py", filename);

    /* data table: one "<vec-index> <re> <im>" triple per point (im = 0 for a real
       vector), so variable-length vectors group cleanly by the first column. */
    {
        static const char *const names[3] = { "vec", "re", "im" };
        struct py_table tab;
        long nrows = 0;
        for (d = vecs; d; d = d->v_link2)
            nrows += d->v_length;
        if (!py_table_open(&tab, filename_data, bin, names, 3, nrows)) {
#ifdef SHARED_MODULE
            setlocale(LC_NUMERIC, llocale);
#endif
            return;
        }
        for (d = vecs, vi = 0; d; d = d->v_link2, vi++) {
            for (i = 0; i < d->v_length; i++) {
                double row[3];
                row[0] = (double) vi;
                row[1] = isreal(d) ? d->v_realdata[i] : realpart(d->v_compdata[i]);
                row[2] = isreal(d) ? 0.0             : imagpart(d->v_compdata[i]);
                py_table_row(&tab, row);
            }
        }
        py_table_close(&tab);
    }

    if ((file = fopen(filename_py, "w")) == NULL) {
        perror(filename);
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }
    fprintf(file, "#!/usr/bin/env python3\n");
    fprintf(file, "# generated by ngspice 'pyplot -smith' (Enhancement-254)\n");
    fprintf(file, "import numpy as np\n");
    if (have_backend) {
        fprintf(file, "import matplotlib\nmatplotlib.use(");
        quote_python_string(file, backend);
        fprintf(file, ")\n");
    } else if (hardcopy) {
        fprintf(file, "import matplotlib\nmatplotlib.use('Agg')\n");
    }
    fprintf(file, "import matplotlib.pyplot as plt\n");
    if (have_style) {
        fprintf(file, "try:\n    plt.style.use(");
        quote_python_string(file, style);
        fprintf(file, ")\nexcept Exception:\n    pass\n");
    }
    /* names for the legend */
    fprintf(file, "names = [");
    for (d = vecs; d; d = d->v_link2) {
        quote_python_string(file, d->v_name ? d->v_name : "");
        fprintf(file, ", ");
    }
    fprintf(file, "]\n");
    if (have_figsize)
        fprintf(file, "fig, ax = plt.subplots(figsize=(%g, %g))\n", figw, figh);
    else
        fprintf(file, "fig, ax = plt.subplots(figsize=(6.4, 6.4))\n");
    /* --- draw the Smith grid --- */
    fprintf(file, "th = np.linspace(0, 2*np.pi, 512)\n");
    fprintf(file, "ax.plot(np.cos(th), np.sin(th), color='0.35', lw=1.1, zorder=1)\n");
    fprintf(file, "def _rcircle(r):\n"
                  "    c = r/(1.0+r); rad = 1.0/(1.0+r)\n"
                  "    ax.plot(c+rad*np.cos(th), rad*np.sin(th), color='0.75', lw=0.6, zorder=1)\n");
    fprintf(file, "def _xarc(x):\n"
                  "    cx, cy, rad = 1.0, 1.0/x, 1.0/abs(x)\n"
                  "    gx = cx+rad*np.cos(th); gy = cy+rad*np.sin(th)\n"
                  "    m = gx*gx+gy*gy <= 1.0+1e-9\n"
                  "    ax.plot(gx[m], gy[m], color='0.75', lw=0.6, zorder=1)\n");
    fprintf(file, "for r in (0.2, 0.5, 1.0, 2.0, 5.0): _rcircle(r)\n");
    fprintf(file, "for x in (0.2, 0.5, 1.0, 2.0, 5.0):\n    _xarc(x); _xarc(-x)\n");
    fprintf(file, "ax.plot([-1, 1], [0, 0], color='0.75', lw=0.6, zorder=1)\n");
    /* --- plot the data curves --- */
    emit_data_load(file, filename_data, bin);
    fprintf(file, "if d.ndim == 1:\n    d = d.reshape(-1, 3)\n");
    fprintf(file, "for vi in range(len(names)):\n"
                  "    m = d[:, 0] == vi\n"
                  "    if not m.any():\n        continue\n"
                  "    xs = d[m, 1]; ys = d[m, 2]\n"
                  "    lbl = names[vi] if names[vi] else None\n"
                  "    if len(xs) == 1:\n"
                  "        ax.plot(xs, ys, 'o', ms=5, label=lbl, zorder=3)\n"
                  "    else:\n"
                  "        ax.plot(xs, ys, lw=1.6, label=lbl, zorder=3)\n");
    fprintf(file, "ax.set_aspect('equal'); ax.axis('off')\n");
    fprintf(file, "ax.set_xlim(-1.08, 1.08); ax.set_ylim(-1.08, 1.08)\n");
    fprintf(file, "if any(names):\n    ax.legend(loc='upper right', fontsize=8, framealpha=0.8)\n");
    if (title) {
        char *text = title_text(title, vecs->v_plot);
        fprintf(file, "ax.set_title(");
        quote_python_string(file, text);
        fprintf(file, ")\n");
        tfree(text);
    }
    fprintf(file, "fig.tight_layout()\n");
    if (hardcopy) {
        fprintf(file, "fig.savefig(");
        emit_here_path(file, filename);
        fprintf(file, " + '.%s', dpi=110)\n", fmt);
        emit_wrote_line(file, filename, fmt);
    } else {
        fprintf(file, "plt.show()\n");
    }
    (void) fclose(file);

    pyplot_run(python, filename, filename_py, hardcopy, fmt);

#ifdef SHARED_MODULE
    setlocale(LC_NUMERIC, llocale);
#endif
}


/* Enhancement-298: `pyplot -bode|-nyquist|-polar <complex vecs>`. Complex-aware AC
   views: unlike an ordinary `pyplot` (which silently keeps the real part of a
   complex vector), these use the FULL complex value. plotit has evaluated the
   expressions into `vecs`; the data table is one "<vec-index> <freq> <re> <im>"
   row per point (im = 0 for a real vector), grouped by the first column so
   variable-length vectors stay separate. Reuses ft_pyplot()'s file/launch scaffolding
   and the shared pyplot_* settings. */
void
ft_pyplot_ac(const char *filename, const char *title, struct dvec *vecs, int ac_mode)
{
    FILE *file;
    struct dvec *d;
    int i, vi, numVecs;
    bool hardcopy = FALSE, bin, have_style, have_figsize, have_backend;
    char terminal[BSIZE_SP], python[BSIZE_SP], style[BSIZE_SP];
    char figsize[BSIZE_SP], backend[BSIZE_SP], fmt[16];
    char filename_data[1024], filename_py[1024];
    double figw = 0.0, figh = 0.0;
    const char *modename = ac_mode == AC_BODE ? "-bode"
                         : ac_mode == AC_NYQUIST ? "-nyquist" : "-polar";

#ifdef SHARED_MODULE
    char *llocale = setlocale(LC_NUMERIC, NULL);
    setlocale(LC_NUMERIC, "C");
#endif

    for (d = vecs, numVecs = 0; d; d = d->v_link2)
        numVecs++;
    if (numVecs < 1) {
        fprintf(cp_err, "Error: pyplot %s needs at least one vector.\n", modename);
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }

    /* same terminal / interpreter / backend / style / figsize handling as ft_pyplot */
    fmt[0] = '\0';
    if (cp_getvar("pyplot_terminal", CP_STRING, terminal, sizeof(terminal))) {
        if (cieq(terminal, "png") || cieq(terminal, "png/quit")) {
            strcpy(fmt, "png"); hardcopy = TRUE;
        } else if (cieq(terminal, "svg") || cieq(terminal, "svg/quit")) {
            strcpy(fmt, "svg"); hardcopy = TRUE;
        } else if (cieq(terminal, "pdf") || cieq(terminal, "pdf/quit")) {
            strcpy(fmt, "pdf"); hardcopy = TRUE;
        }
    }
    if (!cp_getvar("pyplot_python", CP_STRING, python, sizeof(python)))
        strcpy(python, "python3");
    have_backend = cp_getvar("pyplot_backend", CP_STRING, backend, sizeof(backend))
                   ? TRUE : FALSE;
    have_figsize = FALSE;
    if (cp_getvar("pyplot_figsize", CP_STRING, figsize, sizeof(figsize))) {
        if (sscanf(figsize, "%lf%*[ ,xX]%lf", &figw, &figh) == 2
                && figw > 0.0 && figh > 0.0)
            have_figsize = TRUE;
    }
    have_style = cp_getvar("pyplot_style", CP_STRING, style, sizeof(style)) ? TRUE : FALSE;
    if (have_style && cieq(style, "dark"))
        strcpy(style, "dark_background");

    bin = py_export_binary();                     /* Enhancement-549 */
    py_table_name(filename_data, sizeof filename_data, filename, bin);
    snprintf(filename_py, sizeof(filename_py), "%s.py", filename);

    /* data table: one "<vec-index> <freq> <re> <im>" row per point. */
    {
        const char *names[4] = { "vec", "freq", "re", "im" };
        struct py_table tab;
        long nrows = 0;
        if (vecs->v_scale && vecs->v_scale->v_name)
            names[1] = vecs->v_scale->v_name;
        for (d = vecs; d; d = d->v_link2)
            nrows += d->v_length;
        if (!py_table_open(&tab, filename_data, bin, names, 4, nrows)) {
#ifdef SHARED_MODULE
            setlocale(LC_NUMERIC, llocale);
#endif
            return;
        }
        for (d = vecs, vi = 0; d; d = d->v_link2, vi++) {
            struct dvec *sc = d->v_scale;
            for (i = 0; i < d->v_length; i++) {
                double row[4];
                row[0] = (double) vi;
                row[1] = (sc && i < sc->v_length)
                    ? (isreal(sc) ? sc->v_realdata[i] : realpart(sc->v_compdata[i]))
                    : (double) i;
                row[2] = isreal(d) ? d->v_realdata[i] : realpart(d->v_compdata[i]);
                row[3] = isreal(d) ? 0.0             : imagpart(d->v_compdata[i]);
                py_table_row(&tab, row);
            }
        }
        py_table_close(&tab);
    }

    if ((file = fopen(filename_py, "w")) == NULL) {
        perror(filename);
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }
    fprintf(file, "#!/usr/bin/env python3\n");
    fprintf(file, "# generated by ngspice 'pyplot %s' (Enhancement-298)\n", modename);
    fprintf(file, "import numpy as np\n");
    if (have_backend) {
        fprintf(file, "import matplotlib\nmatplotlib.use(");
        quote_python_string(file, backend);
        fprintf(file, ")\n");
    } else if (hardcopy) {
        fprintf(file, "import matplotlib\nmatplotlib.use('Agg')\n");
    }
    fprintf(file, "import matplotlib.pyplot as plt\n");
    if (have_style) {
        fprintf(file, "try:\n    plt.style.use(");
        quote_python_string(file, style);
        fprintf(file, ")\nexcept Exception:\n    pass\n");
    }
    fprintf(file, "names = [");
    for (d = vecs; d; d = d->v_link2) {
        quote_python_string(file, d->v_name ? d->v_name : "");
        fprintf(file, ", ");
    }
    fprintf(file, "]\n");
    emit_data_load(file, filename_data, bin);
    fprintf(file, "if d.ndim == 1:\n    d = d.reshape(-1, 4)\n");

    if (ac_mode == AC_BODE) {
        /* stacked magnitude (dB) / phase (deg) vs frequency (log f) */
        if (have_figsize)
            fprintf(file, "fig, ax = plt.subplots(2, 1, sharex=True, figsize=(%g, %g))\n",
                    figw, figh);
        else
            fprintf(file, "fig, ax = plt.subplots(2, 1, sharex=True, figsize=(7.0, 5.6))\n");
        fprintf(file, "for vi in range(len(names)):\n"
                      "    m = d[:, 0] == vi\n"
                      "    if not m.any():\n        continue\n"
                      "    f = d[m, 1]; z = d[m, 2] + 1j*d[m, 3]\n"
                      "    lbl = names[vi] if names[vi] else None\n"
                      "    ax[0].plot(f, 20*np.log10(np.maximum(np.abs(z), 1e-30)), label=lbl)\n"
                      "    ax[1].plot(f, np.degrees(np.unwrap(np.angle(z))))\n");
        fprintf(file, "for a in ax:\n    a.set_xscale('log'); a.grid(True, which='both')\n");
        /* Enhancement-551: `10 Hz ... 1 MHz` along the shared frequency axis */
        fprintf(file, "from matplotlib.ticker import EngFormatter\n");
        fprintf(file, "ax[1].xaxis.set_major_formatter(EngFormatter(unit='Hz'))\n");
        fprintf(file, "ax[0].set_ylabel('Magnitude [dB]')\n");
        fprintf(file, "ax[1].set_ylabel('Phase [deg]')\n");
        fprintf(file, "ax[1].set_xlabel('Frequency [Hz]')\n");
        fprintf(file, "if any(names):\n    ax[0].legend()\n");
    } else if (ac_mode == AC_NYQUIST) {
        if (have_figsize)
            fprintf(file, "fig, ax = plt.subplots(figsize=(%g, %g))\n", figw, figh);
        else
            fprintf(file, "fig, ax = plt.subplots(figsize=(6.4, 6.0))\n");
        fprintf(file, "for vi in range(len(names)):\n"
                      "    m = d[:, 0] == vi\n"
                      "    if not m.any():\n        continue\n"
                      "    lbl = names[vi] if names[vi] else None\n"
                      "    ax.plot(d[m, 2], d[m, 3], lw=1.6, label=lbl)\n");
        fprintf(file, "ax.axhline(0, color='0.6', lw=0.6); ax.axvline(0, color='0.6', lw=0.6)\n");
        fprintf(file, "ax.set_aspect('equal', 'datalim'); ax.grid(True)\n");
        fprintf(file, "ax.set_xlabel('Real'); ax.set_ylabel('Imag')\n");
        fprintf(file, "if any(names):\n    ax.legend()\n");
    } else { /* AC_POLAR */
        if (have_figsize)
            fprintf(file, "fig, ax = plt.subplots(subplot_kw={'projection':'polar'}, "
                          "figsize=(%g, %g))\n", figw, figh);
        else
            fprintf(file, "fig, ax = plt.subplots(subplot_kw={'projection':'polar'}, "
                          "figsize=(6.4, 6.4))\n");
        fprintf(file, "for vi in range(len(names)):\n"
                      "    m = d[:, 0] == vi\n"
                      "    if not m.any():\n        continue\n"
                      "    z = d[m, 2] + 1j*d[m, 3]\n"
                      "    lbl = names[vi] if names[vi] else None\n"
                      "    ax.plot(np.angle(z), np.abs(z), lw=1.6, label=lbl)\n");
        fprintf(file, "ax.grid(True)\n");
        fprintf(file, "if any(names):\n    ax.legend(loc='upper right', fontsize=8)\n");
    }

    if (title) {
        char *text = title_text(title, vecs->v_plot);
        fprintf(file, "fig.suptitle(");
        quote_python_string(file, text);
        fprintf(file, ")\n");
        tfree(text);
    }
    fprintf(file, "fig.tight_layout()\n");
    if (hardcopy) {
        fprintf(file, "fig.savefig(");
        emit_here_path(file, filename);
        fprintf(file, " + '.%s', dpi=110)\n", fmt);
        emit_wrote_line(file, filename, fmt);
    } else {
        fprintf(file, "plt.show()\n");
    }
    (void) fclose(file);

    pyplot_run(python, filename, filename_py, hardcopy, fmt);

#ifdef SHARED_MODULE
    setlocale(LC_NUMERIC, llocale);
#endif
}


/* Read a scalar metric published by the `eye` command as a length-1 vector in
   the current plot; return `dflt` if it is absent. */
static double
eye_scalar(const char *name, double dflt)
{
    struct dvec *v = vec_get(name);
    if (v && v->v_length > 0)
        return isreal(v) ? v->v_realdata[0] : realpart(v->v_compdata[0]);
    return dflt;
}


/* Enhancement-208: `pyplot -eye`. The `eye` command (Enhancement-207) has just
   folded the waveform into the current 'eye' plot -- `eye_wave` vs `eye_t` plus
   the scalar metrics (eye_ui, eye_threshold, eye_height, eye_width, ...). Render
   those folded samples as a persistence-style 2-D-histogram eye diagram annotated
   with the metrics, reusing ft_pyplot()'s file/launch mechanism and the same
   pyplot_* settings (terminal, python, backend, style, figsize). */
void
ft_pyplot_eye(const char *filename, const char *expr)
{
    FILE *file;
    struct dvec *ew, *et;
    int i;
    bool hardcopy = FALSE, bin, have_style, have_figsize, have_backend, dark;
    char terminal[BSIZE_SP], python[BSIZE_SP], style[BSIZE_SP];
    char figsize[BSIZE_SP], backend[BSIZE_SP], fmt[16];
    char filename_data[1024], filename_py[1024];
    double figw = 0.0, figh = 0.0;
    double ui, thr, eh, ewid, ewb, jr, amp;
    const char *acol, *wcol, *lcol;   /* annotation colours (theme-aware) */

#ifdef SHARED_MODULE
    char *llocale = setlocale(LC_NUMERIC, NULL);
    setlocale(LC_NUMERIC, "C");
#endif

    /* the folded eye must be present (the `eye` command ran first). */
    ew = vec_get("eye_wave");
    et = vec_get("eye_t");
    if (!ew || !et || ew->v_length < 2 || et->v_length < 2) {
        fprintf(cp_err, "Error: pyplot -eye found no folded eye "
                        "('eye_wave'/'eye_t') -- did the eye analysis succeed?\n");
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }

    ui  = eye_scalar("eye_ui", 1.0);
    thr = eye_scalar("eye_threshold", 0.0);
    eh  = eye_scalar("eye_height", 0.0);
    ewid = eye_scalar("eye_width", 0.0);
    ewb = eye_scalar("eye_width_ber12", 0.0);
    jr  = eye_scalar("eye_jitter_rms", 0.0);
    amp = eye_scalar("eye_amplitude", 0.0);

    bin = py_export_binary();                     /* Enhancement-549 */
    py_table_name(filename_data, sizeof filename_data, filename, bin);
    snprintf(filename_py, sizeof(filename_py), "%s.py", filename);

    /* same terminal / interpreter / backend / style / figsize handling as ft_pyplot */
    fmt[0] = '\0';
    if (cp_getvar("pyplot_terminal", CP_STRING, terminal, sizeof(terminal))) {
        if (cieq(terminal, "png") || cieq(terminal, "png/quit")) {
            strcpy(fmt, "png"); hardcopy = TRUE;
        } else if (cieq(terminal, "svg") || cieq(terminal, "svg/quit")) {
            strcpy(fmt, "svg"); hardcopy = TRUE;
        } else if (cieq(terminal, "pdf") || cieq(terminal, "pdf/quit")) {
            strcpy(fmt, "pdf"); hardcopy = TRUE;
        }
    }
    if (!cp_getvar("pyplot_python", CP_STRING, python, sizeof(python)))
        strcpy(python, "python3");
    have_backend = cp_getvar("pyplot_backend", CP_STRING, backend, sizeof(backend))
                   ? TRUE : FALSE;
    have_figsize = FALSE;
    if (cp_getvar("pyplot_figsize", CP_STRING, figsize, sizeof(figsize))) {
        if (sscanf(figsize, "%lf%*[ ,xX]%lf", &figw, &figh) == 2
                && figw > 0.0 && figh > 0.0)
            have_figsize = TRUE;
    }
    have_style = cp_getvar("pyplot_style", CP_STRING, style, sizeof(style)) ? TRUE : FALSE;
    if (have_style && cieq(style, "dark"))
        strcpy(style, "dark_background");
    /* on a dark ground the open-eye area (empty hist2d cells show the figure
       facecolor) is dark, so annotations must be light -- and vice versa. */
    dark = have_style && (strstr(style, "dark") != NULL);
    acol = dark ? "white"   : "black";
    wcol = dark ? "#9be9ff" : "#0b5fa5";
    lcol = dark ? "0.85"    : "0.25";

    /* data table: the folded (eye_t, eye_wave) sample pairs. */
    {
        static const char *const names[2] = { "eye_t", "eye_wave" };
        struct py_table tab;
        int nrow = (et->v_length < ew->v_length) ? et->v_length : ew->v_length;
        if (!py_table_open(&tab, filename_data, bin, names, 2, nrow)) {
#ifdef SHARED_MODULE
            setlocale(LC_NUMERIC, llocale);
#endif
            return;
        }
        for (i = 0; i < nrow; i++) {
            double row[2];
            row[0] = isreal(et) ? et->v_realdata[i] : realpart(et->v_compdata[i]);
            row[1] = isreal(ew) ? ew->v_realdata[i] : realpart(ew->v_compdata[i]);
            py_table_row(&tab, row);
        }
        py_table_close(&tab);
    }

    /* matplotlib script: a persistence-style 2-D-histogram eye. */
    if ((file = fopen(filename_py, "w")) == NULL) {
        perror(filename);
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }
    fprintf(file, "#!/usr/bin/env python3\n");
    fprintf(file, "# generated by ngspice 'pyplot -eye' (Enhancement-208)\n");
    fprintf(file, "import numpy as np\n");
    if (have_backend) {
        fprintf(file, "import matplotlib\nmatplotlib.use(");
        quote_python_string(file, backend);
        fprintf(file, ")\n");
    } else if (hardcopy) {
        fprintf(file, "import matplotlib\nmatplotlib.use('Agg')\n");
    }
    fprintf(file, "import matplotlib.pyplot as plt\n");
    fprintf(file, "from matplotlib.colors import LogNorm\n");
    if (have_style) {
        fprintf(file, "try:\n    plt.style.use(");
        quote_python_string(file, style);
        fprintf(file, ")\nexcept Exception:\n    pass\n");
    }
    emit_data_load(file, filename_data, bin);
    fprintf(file, "if d.ndim == 1:\n    d = d.reshape(-1, 2)\n");
    fprintf(file, "t = d[:, 0]; v = d[:, 1]\n");
    fprintf(file, "ui = %e; thr = %e; eh = %e; ew = %e; ewb = %e; jr = %e; amp = %e\n",
            ui, thr, eh, ewid, ewb, jr, amp);
    if (have_figsize)
        fprintf(file, "fig, ax = plt.subplots(figsize=(%g, %g))\n", figw, figh);
    else
        fprintf(file, "fig, ax = plt.subplots(figsize=(8.0, 4.6))\n");
    fprintf(file, "vlo = float(np.min(v)); vhi = float(np.max(v))\n");
    fprintf(file, "pad = 0.08 * (vhi - vlo + 1e-30)\n");
    fprintf(file, "h = ax.hist2d(t, v, bins=[400, 240], cmap='turbo', norm=LogNorm(),\n");
    fprintf(file, "              range=[[0.0, 2.0*ui], [vlo - pad, vhi + pad]], cmin=1)\n");
    fprintf(file, "cb = fig.colorbar(h[3], ax=ax, pad=0.01)\n");
    fprintf(file, "cb.set_label('sample density (persistence, log)')\n");
    /* after folding, the crossings land at 0.5 UI and 1.5 UI; the eye centre
       (sampling instant, widest opening) sits at 1.0 UI. */
    fprintf(file, "xc = ui\n");
    fprintf(file, "ax.axhline(thr, color='%s', lw=0.8, ls='--', alpha=0.7)\n", lcol);
    fprintf(file, "ax.axvline(xc, color='%s', lw=0.9, ls=':', alpha=0.6)\n", lcol);
    fprintf(file, "if eh > 0:\n");
    fprintf(file, "    ax.annotate('', xy=(xc, thr+eh/2.0), xytext=(xc, thr-eh/2.0),\n");
    fprintf(file, "                arrowprops=dict(arrowstyle='<->', color='%s', lw=1.6))\n", acol);
    fprintf(file, "    ax.text(xc + 0.02*ui, thr + eh/2.0, f'  eye height {eh:.3g}',\n");
    fprintf(file, "            color='%s', fontsize=9, va='center', ha='left')\n", acol);
    fprintf(file, "if ew > 0:\n");
    fprintf(file, "    ax.annotate('', xy=(xc - ew/2.0, thr), xytext=(xc + ew/2.0, thr),\n");
    fprintf(file, "                arrowprops=dict(arrowstyle='<->', color='%s', lw=1.4))\n", wcol);
    fprintf(file, "    ax.text(xc, thr - 0.06*(vhi - vlo + 1e-30), f'eye width {ew:.3g} s',\n");
    fprintf(file, "            color='%s', fontsize=9, ha='center', va='top')\n", wcol);
    fprintf(file, "ax.set_xlim(0.0, 2.0*ui)\n");
    fprintf(file, "ax.set_xlabel('time within 2 UI  (s)')\n");
    /* Enhancement-551: `200 ps ... 1 ns` along the folded time axis */
    fprintf(file, "from matplotlib.ticker import EngFormatter\n");
    fprintf(file, "ax.xaxis.set_major_formatter(EngFormatter(unit='s'))\n");
    fprintf(file, "ax.set_ylabel(");
    quote_python_string(file, expr && *expr ? expr : "signal");
    fprintf(file, ")\n");
    fprintf(file, "ax.set_title('Eye diagram  (ngspice `eye`)\\n'\n");
    fprintf(file, "             f'UI {ui:.3g} s   |   eye height {eh:.3g}'\n");
    fprintf(file, "             f'   |   eye width {ew:.3g} s ({100.0*ew/ui:.0f}%% UI)'\n");
    fprintf(file, "             f'   |   jitter {jr:.3g} s rms')\n");
    fprintf(file, "fig.tight_layout()\n");
    if (hardcopy) {
        fprintf(file, "fig.savefig(");
        emit_here_path(file, filename);
        fprintf(file, " + '.%s', dpi=110)\n", fmt);
        emit_wrote_line(file, filename, fmt);
    } else {
        fprintf(file, "plt.show()\n");
    }
    (void) fclose(file);

    pyplot_run(python, filename, filename_py, hardcopy, fmt);

#ifdef SHARED_MODULE
    setlocale(LC_NUMERIC, llocale);
#endif
}
