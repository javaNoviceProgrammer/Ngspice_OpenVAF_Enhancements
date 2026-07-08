# fgetc_examples — the `$fgetc` file-input function (Enhancement-107)

Enhancement-11 gave openvaf-r a full file I/O family (`$fopen`, `$fgets`,
`$fscanf`, `$ftell`, `$feof`, …) but not `$fgetc`. `$fgetc(fd)` reads one
character and returns its integer code, or `-1` (EOF) at end of file.
Enhancement-107 adds it as another `fd → int` file operation.

`fgetc_demo.va` reads a fixed text file character by character: the first two
characters come back as their ASCII codes, and a `while` loop over `$fgetc`
counts and sums the remaining characters, terminating on the `-1` EOF sentinel.
Run: `python3 verify_fgetc.py` (6 checks).
