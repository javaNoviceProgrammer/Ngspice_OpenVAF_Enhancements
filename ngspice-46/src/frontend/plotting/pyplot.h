/*************
 * Header file for pyplot.c (Enhancement-94)
 ************/

#ifndef ngspice_PYPLOT_H
#define ngspice_PYPLOT_H

/* Enhancement-297: ft_pyplot renders ordinary traces (LINE), a value histogram
   (HIST, Enhancement-217) or a magnitude spectrum (FFT) -- all three share the
   figure/style/backend/subplot scaffolding, so they select on a mode rather than
   duplicating it. */
enum py_mode { PYMODE_LINE = 0, PYMODE_HIST = 1, PYMODE_FFT = 2 };

void ft_pyplot(double *xlims, double *ylims,
        double xdel, double ydel,
        const char *filename, const char *title,
        const char *xlabel, const char *ylabel,
        GRIDTYPE gridtype, PLOTTYPE plottype,
        struct dvec *vecs, int mode);

/* Enhancement-208: render the folded eye (eye_wave/eye_t + scalar metrics left
   in the current plot by the `eye` command) as a persistence-style 2-D-histogram
   eye diagram via matplotlib, honouring the same pyplot_* settings as ft_pyplot. */
void ft_pyplot_eye(const char *filename, const char *expr);

/* Enhancement-218: `pyplot -contour <z> <x> <y>` renders a 2-D contour map of a
   quantity z over the (x, y) plane -- the natural view of a 2-D parameter sweep.
   `vecs` is the 3-vector list built by plotit (z first, then x, then y), all of
   equal length (the flattened sweep grid); the plane is triangulated
   (matplotlib tricontourf), so no grid-dimension metadata is needed. Honours the
   same pyplot_* settings as ft_pyplot. */
void ft_pyplot_contour(const char *filename, const char *title, struct dvec *vecs);
void ft_pyplot_smith(const char *filename, const char *title, struct dvec *vecs);

/* Enhancement-298: complex-aware AC views of one or more frequency responses.
   BODE = stacked magnitude(dB)/phase(deg) vs frequency (log f); NYQUIST = imag vs
   real; POLAR = magnitude at phase on a polar projection. Unlike an ordinary
   `pyplot`, these keep the IMAGINARY part instead of silently taking the real one. */
enum ac_mode { AC_BODE = 0, AC_NYQUIST = 1, AC_POLAR = 2 };
void ft_pyplot_ac(const char *filename, const char *title, struct dvec *vecs, int ac_mode);

#endif
