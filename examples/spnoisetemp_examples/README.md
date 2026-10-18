# spnoisetemp_examples — Enhancement-901

`.sp … 1`'s noise parameters: F7 of the
[analyses correctness campaign of 2026-10-16](../../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md).
`span.c` normalised the noise correlation matrix by 4k·`CKTtemp`. The IEEE noise parameters use
T₀ = 290 K, and the noise figure is defined with the source at T₀. At 27 °C a passive two-port's
NF read up to 0.149 dB low and Rn 3.4 % low; at other temperatures more. See
[E-901](../../enhancements_doc/Enhancement-901.md).

The reference is the network itself: every resistor's 4kT/R at its own temperature, folded to
the ports' short-circuit currents, turned into the chain form and normalised by 4kT₀.

- **[1]** A 100 Ω / 100 Ω attenuator between 50 Ω ports at 27 °C: NF, NFmin and Rn by the IEEE
  definition (NF 8.8804 dB).
- **[2]** The same at 16.85 °C, T = T₀: NF = 10·log₁₀(1/G_a) = 8.7506 dB, as before.
- **[3]** A series 100 Ω at 27 °C: Rn = R·T/T₀ = 103.5 Ω.
- **[4]** A resistive T network at 125 °C and at −40 °C.
- **[5]** An active stage (a VCCS with resistors and capacitors) at 60 °C: NF, NFmin, Rn and
  SOpt at four frequencies.
- **[6]** A series resistor at `temp=-196` in a circuit at 27 °C: NF follows the resistor's own
  temperature.
- **[7]** Cy is unchanged: 4kT·Re(Y) at the circuit's temperature.

Run: `python3 verify_spnoisetemp.py` (7 checks per solver). On the E-899 binaries 5 fail; [2]
and [7] pass.
