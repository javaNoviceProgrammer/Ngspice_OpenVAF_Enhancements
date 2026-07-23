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
#else
#include <unistd.h>
#endif
#include <locale.h>

#define PY_MAXVECTORS 64


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
    FILE *file, *file_data;
    struct dvec *v;
    int i, col, numVecs, err, nper, nrows, row;
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
    char buf[2 * 1024 + BSIZE_SP];
    char *text;
    double figw = 0.0, figh = 0.0;
    bool hardcopy = FALSE;

    NG_IGNORE(xdel);
    NG_IGNORE(ydel);

#ifdef SHARED_MODULE
    char *llocale = setlocale(LC_NUMERIC, NULL);
    setlocale(LC_NUMERIC, "C");
#endif

    snprintf(filename_data, sizeof(filename_data), "%s.data", filename);
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
    if ((file_data = fopen(filename_data, "w")) == NULL) {
        perror(filename);
        return;
    }
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
    for (i = 0; i < datarows; i++) {
        for (v = vecs; v; v = v->v_link2) {
            struct dvec *sc = v->v_scale;
            double xval = (sc && i < sc->v_length)
                ? (isreal(sc) ? sc->v_realdata[i] : realpart(sc->v_compdata[i]))
                : NAN;
            double yval = (i < v->v_length)
                ? (isreal(v) ? v->v_realdata[i] : realpart(v->v_compdata[i]))
                : NAN;
            fprintf(file_data, "%e %e ", xval, yval);
        }
        fprintf(file_data, "\n");
    }
    (void) fclose(file_data);

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
    /* Enhancement-98: apply a matplotlib style sheet if requested (ignore an
       unknown name rather than aborting the plot). */
    if (have_style) {
        fprintf(file, "try:\n    plt.style.use(");
        quote_python_string(file, style);
        fprintf(file, ")\nexcept Exception:\n    pass\n");
    }
    fprintf(file, "d = np.loadtxt(");
    quote_python_string(file, filename_data);
    fprintf(file, ")\n");
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

    /* Enhancement-297: the FFT window (numpy) chosen by pyplot_fft_window. */
    const char *winexpr = "np.hanning(_N)";
    if (fft) {
        if (cieq(fftwin, "hamming"))       winexpr = "np.hamming(_N)";
        else if (cieq(fftwin, "blackman")) winexpr = "np.blackman(_N)";
        else if (cieq(fftwin, "rect") || cieq(fftwin, "none")
                 || cieq(fftwin, "boxcar")) winexpr = "np.ones(_N)";
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
        fprintf(file, "axes[%d, 0].", row);
        if (hist) {
            /* Enhancement-217: the VALUE column (col+1), NaN-filtered so vectors
               of unequal length (padded with NaN in the data table) histogram
               cleanly. Overlaid histograms on one axis get alpha transparency. */
            fprintf(file, "hist(d[:, %d][~np.isnan(d[:, %d])], ", col + 1, col + 1);
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
        } else if (boxes)
            fprintf(file, "step(d[:, %d], d[:, %d], where='mid', %s", col, col + 1, lwarg);
        else if (markers)
            fprintf(file, "plot(d[:, %d], d[:, %d], marker='.', linestyle='None', ",
                    col, col + 1);
        else if (linemarkers) {
            /* Enhancement-296: line + a cycling marker shape, so overlaid traces
               are distinguishable without colour. */
            static const char *mk[] = { "o", "s", "^", "D", "v", "*", "P", "X" };
            fprintf(file, "plot(d[:, %d], d[:, %d], marker='%s', markevery=0.1, %s",
                    col, col + 1, mk[i % 8], lwarg);
        } else
            fprintf(file, "plot(d[:, %d], d[:, %d], %s", col, col + 1, lwarg);
        fprintf(file, "label=");
        quote_python_string(file, v->v_name ? v->v_name : "");
        fprintf(file, ")\n");
        col += 2;
        i++;
    }

    /* Per-axis cosmetics applied to every panel; the x-label goes on the
       bottom panel only, the title becomes the figure suptitle. */
    fprintf(file, "for _ax in axes[:, 0]:\n");
    /* Enhancement-217: for a histogram the y-axis is the count (or density); for a
       line plot it is the signal type passed in as `ylabel`. */
    if (fft) {
        fprintf(file, "    _ax.set_ylabel('%s')\n",
                fftdb ? "Magnitude [dB]" : "Magnitude");
    } else if (hist) {
        fprintf(file, "    _ax.set_ylabel('%s')\n", histdensity ? "density" : "count");
    } else if (ylabel) {
        text = cp_unquote(ylabel);
        fprintf(file, "    _ax.set_ylabel(");
        quote_python_string(file, text);
        fprintf(file, ")\n");
        tfree(text);
    }
    if (xlog || (fft && fftlogf))
        fprintf(file, "    _ax.set_xscale('log')\n");
    if (ylog)
        fprintf(file, "    _ax.set_yscale('log')\n");
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
    if (xlims)
        fprintf(file, "    _ax.set_xlim(%e, %e)\n", xlims[0], xlims[1]);
    if (ylims && !ylog)
        fprintf(file, "    _ax.set_ylim(%e, %e)\n", ylims[0], ylims[1]);
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
    /* Enhancement-217: a histogram's x-axis is the signal VALUE (the `ylabel` type),
       and the panels do not share it, so it is labelled on every panel; a line
       plot's shared time/frequency axis is labelled on the bottom panel only. */
    if (fft) {
        fprintf(file, "axes[-1, 0].set_xlabel('Frequency [Hz]')\n");
    } else {
        if (hist && ylabel) {
            text = cp_unquote(ylabel);
            fprintf(file, "    _ax.set_xlabel(");
            quote_python_string(file, text);
            fprintf(file, ")\n");
            tfree(text);
        }
        if (!hist && xlabel) {
            text = cp_unquote(xlabel);
            fprintf(file, "axes[-1, 0].set_xlabel(");
            quote_python_string(file, text);
            fprintf(file, ")\n");
            tfree(text);
        }
    }
    if (title) {
        text = cp_unquote(title);
        fprintf(file, "fig.suptitle(");
        quote_python_string(file, text);
        fprintf(file, ")\n");
        tfree(text);
    }
    fprintf(file, "fig.tight_layout()\n");
    if (hardcopy) {
        /* Enhancement-296: `pyplot_dpi` (default 100) and `pyplot_transparent`. */
        fprintf(file, "fig.savefig(");
        quote_python_string(file, filename);
        fprintf(file, " + '.%s', dpi=%d%s)\n", fmt, dpi,
                transparent ? ", transparent=True" : "");
        fprintf(file, "print('pyplot: wrote %s.%s')\n", filename, fmt);
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

    /* Run it: synchronously for a PNG, in the background for a window. */
#if defined(__MINGW32__) || defined(_MSC_VER)
    if (hardcopy)
        (void) snprintf(buf, sizeof(buf), "%s %s", python, filename_py);
    else
        (void) snprintf(buf, sizeof(buf), "start /B %s %s", python, filename_py);
    _flushall();
#else
    if (hardcopy)
        (void) snprintf(buf, sizeof(buf), "%s %s", python, filename_py);
    else
        (void) snprintf(buf, sizeof(buf), "%s %s &", python, filename_py);
#endif
    err = system(buf);
    if (err == -1)
        fprintf(cp_err, "Error: could not run '%s'.\n", buf);

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
    FILE *file, *file_data;
    struct dvec *z, *x, *y;
    int i, n, numVecs, err;
    bool hardcopy = FALSE, have_style, have_figsize, have_backend, lines;
    int levels;
    char terminal[BSIZE_SP], python[BSIZE_SP], style[BSIZE_SP];
    char figsize[BSIZE_SP], backend[BSIZE_SP], cmap[BSIZE_SP], fmt[16];
    char filename_data[1024], filename_py[1024];
    char buf[2 * 1024 + BSIZE_SP];
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

    snprintf(filename_data, sizeof(filename_data), "%s.data", filename);
    snprintf(filename_py, sizeof(filename_py), "%s.py", filename);

    /* data table: one (x, y, z) triple per row (real part for complex data). */
    if ((file_data = fopen(filename_data, "w")) == NULL) {
        perror(filename);
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }
    for (i = 0; i < n; i++) {
        double xv = isreal(x) ? x->v_realdata[i] : realpart(x->v_compdata[i]);
        double yv = isreal(y) ? y->v_realdata[i] : realpart(y->v_compdata[i]);
        double zv = isreal(z) ? z->v_realdata[i] : realpart(z->v_compdata[i]);
        fprintf(file_data, "%e %e %e\n", xv, yv, zv);
    }
    (void) fclose(file_data);

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
    fprintf(file, "d = np.loadtxt(");
    quote_python_string(file, filename_data);
    fprintf(file, ")\n");
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
    fprintf(file, "ax.set_xlabel(");
    quote_python_string(file, x->v_name ? x->v_name : "x");
    fprintf(file, ")\n");
    fprintf(file, "ax.set_ylabel(");
    quote_python_string(file, y->v_name ? y->v_name : "y");
    fprintf(file, ")\n");
    if (title) {
        char *text = cp_unquote(title);
        fprintf(file, "ax.set_title(");
        quote_python_string(file, text);
        fprintf(file, ")\n");
        tfree(text);
    }
    fprintf(file, "fig.tight_layout()\n");
    if (hardcopy) {
        fprintf(file, "fig.savefig(");
        quote_python_string(file, filename);
        fprintf(file, " + '.%s', dpi=110)\n", fmt);
        fprintf(file, "print('pyplot: wrote %s.%s')\n", filename, fmt);
    } else {
        fprintf(file, "plt.show()\n");
    }
    (void) fclose(file);

    /* run it: synchronously for a file, in the background for a window. */
#if defined(__MINGW32__) || defined(_MSC_VER)
    if (hardcopy)
        (void) snprintf(buf, sizeof(buf), "%s %s", python, filename_py);
    else
        (void) snprintf(buf, sizeof(buf), "start /B %s %s", python, filename_py);
    _flushall();
#else
    if (hardcopy)
        (void) snprintf(buf, sizeof(buf), "%s %s", python, filename_py);
    else
        (void) snprintf(buf, sizeof(buf), "%s %s &", python, filename_py);
#endif
    err = system(buf);
    if (err == -1)
        fprintf(cp_err, "Error: could not run '%s'.\n", buf);

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
    FILE *file, *file_data;
    struct dvec *d;
    int i, vi, numVecs, err;
    bool hardcopy = FALSE, have_style, have_figsize, have_backend;
    char terminal[BSIZE_SP], python[BSIZE_SP], style[BSIZE_SP];
    char figsize[BSIZE_SP], backend[BSIZE_SP], fmt[16];
    char filename_data[1024], filename_py[1024];
    char buf[2 * 1024 + BSIZE_SP];
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

    snprintf(filename_data, sizeof(filename_data), "%s.data", filename);
    snprintf(filename_py, sizeof(filename_py), "%s.py", filename);

    /* data table: one "<vec-index> <re> <im>" triple per point (im = 0 for a real
       vector), so variable-length vectors group cleanly by the first column. */
    if ((file_data = fopen(filename_data, "w")) == NULL) {
        perror(filename);
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }
    for (d = vecs, vi = 0; d; d = d->v_link2, vi++) {
        for (i = 0; i < d->v_length; i++) {
            double re = isreal(d) ? d->v_realdata[i] : realpart(d->v_compdata[i]);
            double im = isreal(d) ? 0.0             : imagpart(d->v_compdata[i]);
            fprintf(file_data, "%d %e %e\n", vi, re, im);
        }
    }
    (void) fclose(file_data);

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
    fprintf(file, "d = np.loadtxt(");
    quote_python_string(file, filename_data);
    fprintf(file, ")\n");
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
        char *text = cp_unquote(title);
        fprintf(file, "ax.set_title(");
        quote_python_string(file, text);
        fprintf(file, ")\n");
        tfree(text);
    }
    fprintf(file, "fig.tight_layout()\n");
    if (hardcopy) {
        fprintf(file, "fig.savefig(");
        quote_python_string(file, filename);
        fprintf(file, " + '.%s', dpi=110)\n", fmt);
        fprintf(file, "print('pyplot: wrote %s.%s')\n", filename, fmt);
    } else {
        fprintf(file, "plt.show()\n");
    }
    (void) fclose(file);

    /* run it: synchronously for a file, in the background for a window. */
#if defined(__MINGW32__) || defined(_MSC_VER)
    if (hardcopy)
        (void) snprintf(buf, sizeof(buf), "%s %s", python, filename_py);
    else
        (void) snprintf(buf, sizeof(buf), "start /B %s %s", python, filename_py);
    _flushall();
#else
    if (hardcopy)
        (void) snprintf(buf, sizeof(buf), "%s %s", python, filename_py);
    else
        (void) snprintf(buf, sizeof(buf), "%s %s &", python, filename_py);
#endif
    err = system(buf);
    if (err == -1)
        fprintf(cp_err, "Error: could not run '%s'.\n", buf);

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
    FILE *file, *file_data;
    struct dvec *d;
    int i, vi, numVecs, err;
    bool hardcopy = FALSE, have_style, have_figsize, have_backend;
    char terminal[BSIZE_SP], python[BSIZE_SP], style[BSIZE_SP];
    char figsize[BSIZE_SP], backend[BSIZE_SP], fmt[16];
    char filename_data[1024], filename_py[1024];
    char buf[2 * 1024 + BSIZE_SP];
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

    snprintf(filename_data, sizeof(filename_data), "%s.data", filename);
    snprintf(filename_py, sizeof(filename_py), "%s.py", filename);

    if ((file_data = fopen(filename_data, "w")) == NULL) {
        perror(filename);
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }
    for (d = vecs, vi = 0; d; d = d->v_link2, vi++) {
        struct dvec *sc = d->v_scale;
        for (i = 0; i < d->v_length; i++) {
            double fr = (sc && i < sc->v_length)
                ? (isreal(sc) ? sc->v_realdata[i] : realpart(sc->v_compdata[i]))
                : (double) i;
            double re = isreal(d) ? d->v_realdata[i] : realpart(d->v_compdata[i]);
            double im = isreal(d) ? 0.0             : imagpart(d->v_compdata[i]);
            fprintf(file_data, "%d %e %e %e\n", vi, fr, re, im);
        }
    }
    (void) fclose(file_data);

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
    fprintf(file, "d = np.loadtxt(");
    quote_python_string(file, filename_data);
    fprintf(file, ")\n");
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
        char *text = cp_unquote(title);
        fprintf(file, "fig.suptitle(");
        quote_python_string(file, text);
        fprintf(file, ")\n");
        tfree(text);
    }
    fprintf(file, "fig.tight_layout()\n");
    if (hardcopy) {
        fprintf(file, "fig.savefig(");
        quote_python_string(file, filename);
        fprintf(file, " + '.%s', dpi=110)\n", fmt);
        fprintf(file, "print('pyplot: wrote %s.%s')\n", filename, fmt);
    } else {
        fprintf(file, "plt.show()\n");
    }
    (void) fclose(file);

#if defined(__MINGW32__) || defined(_MSC_VER)
    if (hardcopy)
        (void) snprintf(buf, sizeof(buf), "%s %s", python, filename_py);
    else
        (void) snprintf(buf, sizeof(buf), "start /B %s %s", python, filename_py);
    _flushall();
#else
    if (hardcopy)
        (void) snprintf(buf, sizeof(buf), "%s %s", python, filename_py);
    else
        (void) snprintf(buf, sizeof(buf), "%s %s &", python, filename_py);
#endif
    err = system(buf);
    if (err == -1)
        fprintf(cp_err, "Error: could not run '%s'.\n", buf);

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
    FILE *file, *file_data;
    struct dvec *ew, *et;
    int i, err;
    bool hardcopy = FALSE, have_style, have_figsize, have_backend, dark;
    char terminal[BSIZE_SP], python[BSIZE_SP], style[BSIZE_SP];
    char figsize[BSIZE_SP], backend[BSIZE_SP], fmt[16];
    char filename_data[1024], filename_py[1024];
    char buf[2 * 1024 + BSIZE_SP];
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

    snprintf(filename_data, sizeof(filename_data), "%s.data", filename);
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
    if ((file_data = fopen(filename_data, "w")) == NULL) {
        perror(filename);
#ifdef SHARED_MODULE
        setlocale(LC_NUMERIC, llocale);
#endif
        return;
    }
    {
        int nrow = (et->v_length < ew->v_length) ? et->v_length : ew->v_length;
        for (i = 0; i < nrow; i++) {
            double x = isreal(et) ? et->v_realdata[i] : realpart(et->v_compdata[i]);
            double y = isreal(ew) ? ew->v_realdata[i] : realpart(ew->v_compdata[i]);
            fprintf(file_data, "%e %e\n", x, y);
        }
    }
    (void) fclose(file_data);

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
    fprintf(file, "d = np.loadtxt(");
    quote_python_string(file, filename_data);
    fprintf(file, ")\n");
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
        quote_python_string(file, filename);
        fprintf(file, " + '.%s', dpi=110)\n", fmt);
        fprintf(file, "print('pyplot: wrote %s.%s')\n", filename, fmt);
    } else {
        fprintf(file, "plt.show()\n");
    }
    (void) fclose(file);

    /* run it: synchronously for a file, in the background for a window. */
#if defined(__MINGW32__) || defined(_MSC_VER)
    if (hardcopy)
        (void) snprintf(buf, sizeof(buf), "%s %s", python, filename_py);
    else
        (void) snprintf(buf, sizeof(buf), "start /B %s %s", python, filename_py);
    _flushall();
#else
    if (hardcopy)
        (void) snprintf(buf, sizeof(buf), "%s %s", python, filename_py);
    else
        (void) snprintf(buf, sizeof(buf), "%s %s &", python, filename_py);
#endif
    err = system(buf);
    if (err == -1)
        fprintf(cp_err, "Error: could not run '%s'.\n", buf);

#ifdef SHARED_MODULE
    setlocale(LC_NUMERIC, llocale);
#endif
}
