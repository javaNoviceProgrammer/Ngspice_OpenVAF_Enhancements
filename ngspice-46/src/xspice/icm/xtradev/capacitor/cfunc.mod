/* ===========================================================================
FILE    capacitor/cfunc.mod

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

    This file contains the definition of a capacitor code model
    with voltage type initial conditions.

INTERFACES

    cm_capacitor()

REFERENCED FILES

    None.

NON-STANDARD FEATURES

    None.

=========================================================================== */


#define VC  0


void cm_capacitor (ARGS)
{
    Complex_t   ac_gain;
    double      partial;
    double      ramp_factor;
    double      *vc;

    static char *c_zero_error =
        "\n***ERROR***\nCAPACITOR: c = 0 is not a usable value "
        "(the model divides by it).\n";

    /* Enhancement-486: PARAM(c) is a divisor both in AC (-1/w/c) and in the
     * transient integrator below, so c = 0 is a division by zero. It reached the
     * user as "TRAN: Timestep too small; cause unrecorded" -- a message that
     * names neither the parameter nor the model, and that is indistinguishable
     * from an ordinary convergence failure. The built-in C device treats C = 0 as
     * the open circuit it is, but this model's `hd` port answers with a VOLTAGE
     * for a given current and an open circuit has no finite voltage to return,
     * so it cannot follow the built-in; it refuses by name instead.
     *
     * A NEGATIVE c is deliberately NOT guarded. The built-in C device accepts a
     * negative capacitance and produces exactly the sign-inverted response this
     * model produces (verified against C = -1u), so a negative capacitance is a
     * legitimate equivalent-circuit element here, not a value to be rejected. */
    if (PARAM(c) == 0.0) {
        cm_message_send(c_zero_error);
        cm_cexit(1);
    }

    /* Get the ramp factor from the .option ramptime */
    ramp_factor = cm_analog_ramp_factor();

    /* Initialize/access instance specific storage for capacitor voltage */
    if(INIT) {
        cm_analog_alloc(VC, sizeof(double));
        vc = (double *) cm_analog_get_ptr(VC, 0);
        *vc = PARAM(ic) * cm_analog_ramp_factor();
    }
    else {
        vc = (double *) cm_analog_get_ptr(VC, 0);
    }

    /* Compute the output */
    if(ANALYSIS == DC) {
        OUTPUT(cap) = PARAM(ic) * ramp_factor;
        PARTIAL(cap, cap) = 0.0;
    }
    else if(ANALYSIS == AC) {
        ac_gain.real = 0.0;
        ac_gain.imag = -1.0 / RAD_FREQ / PARAM(c);
        AC_GAIN(cap, cap) = ac_gain;
    }
    else if(ANALYSIS == TRANSIENT) {
        if(ramp_factor < 1.0) {
            *vc = PARAM(ic) * ramp_factor;
            OUTPUT(cap) = *vc;
            PARTIAL(cap, cap) = 0.0;
        }
        else {
            cm_analog_integrate(INPUT(cap) / PARAM(c), vc, &partial);
            partial /= PARAM(c);
            OUTPUT(cap) = *vc;
            PARTIAL(cap, cap) = partial;
        }
    }
}

