#ifndef ngspice_COM_HB_H
#define ngspice_COM_HB_H

/* Enhancement-134: harmonic balance. */
void com_hb(wordlist *wl);

/* Enhancement-487: the driven `hb` and the autonomous `hbosc` produce the same
   (2K+1)*N two-sided spectrum, so they publish it through ONE routine rather than
   each growing its own copy -- `hbosc` had no publisher at all and printed a table
   into a session whose current plot was its own startup transient. `plotname` is
   the nutmeg plot type ("hb" / "hbosc"), `plotdesc` the human name shown by
   `setplot`, and `cmd` the command named in the closing hint. When `withf0` is
   true a scalar `oscfreq` vector is added, because for an autonomous circuit the
   frequency is part of the ANSWER rather than an input. */
void hb_publish_spectrum(CKTcircuit *ckt, const struct hbspectrum *sp,
                         const char *plotname, const char *plotdesc,
                         const char *cmd, int withf0);

#endif
