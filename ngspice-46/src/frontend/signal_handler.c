/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Wayne A. Christopher, U. C. Berkeley CAD Group
**********/
/*
 * The signal routines for spice 3 and nutmeg.
 */

#include "ngspice/ngspice.h"
#include "ngspice/ifsim.h"
#include "ngspice/iferrmsg.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/ftedev.h"
#include "ngspice/fteext.h"     /* E-536: ft_optimizing, outp_loop_abort */
#include "ngspice/randnumb.h"   /* E-536: mc_wcd_off, mc_sss_off */
#include "ngspice/osdiitf.h"    /* E-536: OSDImcInterruptReset */
#include "com_aging.h"          /* E-536: aging_internal_reset */
#include <setjmp.h>
#include <signal.h>
#include "signal_handler.h"
#include "plotting/graf.h"

#ifdef SIGTTIN
#include <unistd.h>
#endif

#ifdef HAS_WINGUI
void winmessage(char* new_msg);
#endif

#ifdef HAVE_GNUREADLINE
/* Added GNU Readline Support 11/3/97 -- Andrew Veliath <veliaa@rpi.edu> */
/* from spice3f4 patch to ng-spice. jmr */
#include <readline/readline.h>
#include <readline/history.h>
#endif

#ifdef HAVE_BSDEDITLINE
/* SJB added edit line support 2005-05-05 */
#include <editline/readline.h>
#endif /* HAVE_BSDEDITLINE */

JMP_BUF jbuf;

/* The (void) signal handlers... SIGINT is the only one that gets reset (by
 * cshpar) so it is global. They are ifdef BSD because of the sigmask
 * stuff in sigstop. We set the interrupt flag and return if ft_setflag
 * is TRUE.
 */


/* The purpose of ft_sigintr_cleanup() is to handle all processing of asynchronous
 * signals which require user process context. Some kernel services are not
 * allowed to be called from asynchronous signal handlers. (e.g. mutexes)
 */

void
ft_sigintr_cleanup(void)
{
    /* E-536 (hunt bugs 5/6/12): the LONGJMP above skipped every loop
     * command's cleanup path, and the leaked state silently corrupted
     * whatever the user did next: ft_optimizing left TRUE muted all later
     * output; an interrupted `highsigma -scale` left its sigma inflation
     * (and MC_MODE_SSS) armed, scaling every later draw; an interrupted
     * `wcd` left MC_MODE_WCD pinning every gaussian to a chosen point; a
     * dangling osdimc hold froze all later runs on one Monte-Carlo sample,
     * and a dangling preserve carried the trial sequence through a USER
     * re-source (observed continuing at trial 91828); a half-drawn progress
     * bar kept the terminal line; and an elevated aging_internal_reset made
     * later USER resets keep age records they must drop. Once control is
     * back at the prompt, none of that state is legitimately in progress --
     * reset it all. */
    ft_optimizing = FALSE;
    aging_internal_reset = 0;
    mc_wcd_off();
    mc_sss_off();
    OSDImcInterruptReset();
    outp_loop_abort();

    gr_clean();  /* Clean up plot window */

    /* sjb - what to do for editline???
       The following are not supported in editline */
#if defined(HAVE_GNUREADLINE)
    /*  Clean up readline after catching signals  */
    /*  One or all of these might be superfluous  */
    (void) rl_free_line_state();
    (void) rl_cleanup_after_signal();
    (void) rl_reset_after_signal();
#endif /* defined(HAVE_GNUREADLINE) || defined(HAVE_BSDEDITLINE) */

    /* To restore screen after an interrupt to a plot for instance */
    cp_interactive = TRUE;
    cp_resetcontrol(TRUE);
}


/*  invoke this function upon keyboard interrupt  */
void
ft_sigintr(void)
{
    static int interrupt_counter = 0;

    /* fprintf(cp_err, "Received interrupt.  Handling it  . . . . .\n"); */

    /* Reinstall ft_signintr as the signal handler. */
    (void) signal(SIGINT, (SIGNAL_FUNCTION) ft_sigintr);

    if (ft_intrpt) {    /* check to see if we're being interrupted repeatedly */
        fprintf(cp_err, "\nInterrupted again (ouch)\n");
        interrupt_counter++;
    } else {
        fprintf(cp_err, "\nInterrupted once . . .\n");
        ft_intrpt = TRUE;
        interrupt_counter = 1;
    }

    if (interrupt_counter >= 3) {
        fprintf(cp_err, "\nKilling, since %d interrupts have been requested\n\n", interrupt_counter);
        controlled_exit(1);
    }

    if (ft_setflag) {
        return;     /* just return without aborting simulation if ft_setflag = TRUE */
    }

    /* here we jump to the start of command processing in main() after resetting everything.  */
    cp_background = FALSE;
    LONGJMP(jbuf, 1);
}


void
sigfloat(int code)
{
    fperror("Error", code);
    rewind(cp_out);
    (void) signal(SIGFPE, (SIGNAL_FUNCTION) sigfloat);
    LONGJMP(jbuf, 1);
}

/* Shared handler for SIGTTIN and SIGTTOU.  Restart event handling if caught
 * attempting terminal IO as a background process.
 */

bool cp_background = FALSE;

#ifdef SIGTTIN
void
sigttio(void)
{
    if (cp_cwait) {
        /* Attempted command input/output on the terminal while in background.
         * Set background flag and restart event loop.
         */
        cp_background = TRUE;
        LONGJMP(jbuf, 1);
    } else {
        /* Non-command terminal IO in background. That should never happen.
         * Stop.
         */

        (void) signal(SIGTSTP, SIG_DFL);
        (void) kill(getpid(), SIGTSTP); /* This should stop us */
    }
}

/* Is this a background process? */

void test_background(void)
{
    pid_t terminal_group;
    int   tty;

    tty = open("/dev/tty", O_RDONLY);
    if (tty < 0) {
        cp_background = TRUE; // No controlling terminal, so "in background".
        return;
    }
    terminal_group = tcgetpgrp(tty); // Posix 2001, so portable.
    close(tty);
    cp_background = (terminal_group != getpgrp());
}
#endif

/* This should give a new prompt if cshpar is waiting for input.  */

#ifdef SIGTSTP

void
sigstop(void)
{
    gr_clean();
    (void) signal(SIGTSTP, SIG_DFL);
    (void) kill(getpid(), SIGTSTP); /* This should stop us */
}


void
sigcont(void)
{
    (void) signal(SIGTSTP, (SIGNAL_FUNCTION) sigstop);
    test_background();
    if (cp_cwait)
        LONGJMP(jbuf, 1);
}


#endif


/* Special (void) signal handlers. */

void
sigill(void)
{
    fprintf(cp_err, "\ninternal error -- illegal instruction\n");
    fatal();
}


void
sigbus(void)
{
    fprintf(cp_err, "\ninternal error -- bus error\n");
    fatal();
}


void
sigsegv(void)
{
    fprintf(cp_err, "\ninternal error -- segmentation violation\n");
#ifdef HAS_WINGUI
    winmessage("Fatal error in NGSPICE");
#endif
    fatal();
}

void
sigsegvsh(void)
{
    fprintf(cp_err, "\ninternal error -- segmentation violation\n");
    controlled_exit(EXIT_SEGV);
}


void
sig_sys(void)
{
    fprintf(cp_err, "\ninternal error -- bad argument to system call\n");
    fatal();
}
