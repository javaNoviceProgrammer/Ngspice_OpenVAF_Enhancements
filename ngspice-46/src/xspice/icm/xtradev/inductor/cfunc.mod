/* ===========================================================================
FILE    cfunc.mod

MEMBER OF process XSPICE

Public Domain

Georgia Tech Research Corporation
Atlanta, Georgia 30332
PROJECT A-8503

AUTHORS

    9/12/91  Bill Kuhn

MODIFICATIONS

    <date> <person name> <nature of modifications>

SUMMARY

    This file contains the definition of an inductor code model
    with current initial conditions.

INTERFACES

    cm_inductor()

REFERENCED FILES

    None.

NON-STANDARD FEATURES

    None.

=========================================================================== */


#define LI  0


void cm_inductor (ARGS)
{
    Complex_t   ac_gain;
    double      partial;
    double      ramp_factor;
    double      *li;

    static char *l_zero_error =
        "\n***ERROR***\nINDUCTOR: l = 0 is not a usable value "
        "(the model divides by it).\n";

    /* Enhancement-486: the transient integrator below divides by PARAM(l), so
     * l = 0 is a division by zero that surfaced only as "TRAN: Timestep too
     * small; cause unrecorded", naming neither the parameter nor the model. The
     * built-in L device treats L = 0 as the short it is; this model's `hd` port
     * cannot express that, so it refuses by name. The sibling capacitor model
     * carries the same guard for the same reason.
     *
     * A NEGATIVE l is deliberately NOT guarded: the built-in L device accepts it
     * and diverges in exactly the same way this model does (7.5e+288 against
     * 1.8e+285, both ending in the same timestep abort), so the two agree and
     * there is nothing here that the built-in device treats as an error. */
    if (PARAM(l) == 0.0) {
        cm_message_send(l_zero_error);
        cm_cexit(1);
    }

    /* Get the ramp factor from the .option ramptime */
    ramp_factor = cm_analog_ramp_factor();

    /* Initialize/access instance specific storage for capacitor voltage */
    if(INIT) {
        cm_analog_alloc(LI, sizeof(double));
        li = (double *) cm_analog_get_ptr(LI, 0);
        *li = PARAM(ic) * ramp_factor;
    }
    else {
        li = (double *) cm_analog_get_ptr(LI, 0);
    }

    /* Compute the output */
    if(ANALYSIS == DC) {
        OUTPUT(ind) = PARAM(ic) * ramp_factor;
        PARTIAL(ind, ind) = 0.0;
    }
    else if(ANALYSIS == AC) {
        ac_gain.real = 0.0;
        ac_gain.imag = 1.0 * RAD_FREQ * PARAM(l);
        AC_GAIN(ind, ind) = ac_gain;
    }
    else if(ANALYSIS == TRANSIENT) {
        if(ramp_factor < 1.0) {
            *li = PARAM(ic) * ramp_factor;
            OUTPUT(ind) = *li;
            PARTIAL(ind, ind) = 0.0;
        }
        else {
            cm_analog_integrate(INPUT(ind) / PARAM(l), li, &partial);
            partial /= PARAM(l);
            OUTPUT(ind) = *li;
            PARTIAL(ind, ind) = partial;
        }
    }
}

