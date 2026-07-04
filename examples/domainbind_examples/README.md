# domainbind_examples — domain binding statements (Enhancement-50)

Demonstrates **discipline domain bindings** (`domain continuous;` /
`domain discrete;`, LRM 3.6.2.2) — using the committed `openvaf-r` and
`ngspice-46`.

## What was found

The probe showed `domain` substantially implemented: both bindings parse (the
std header's own `ddiscrete`/`logic` disciplines exercise `domain discrete`
in every compilation), nature-bound disciplines default to continuous, the
domain participates in discipline-compatibility checks (domainless treated
permissively per LRM 3.6.2.3), and discrete nets are rejected in analog
accesses. One LRM rule was unenforced: *"It is an error for a discipline to
have a domain binding of discrete if it has nature bindings"* — accepted
silently.

E-50 adds the validation with a two-label diagnostic pointing at both the
`domain discrete;` binding and the offending nature binding, with an
LRM-citing help note.

## Run

```
python3 verify_domainbind.py
```

Checks (ALL PASS): a custom `domain continuous` discipline with natures
simulates exactly (−1 mA through its 1k contribution); a natureless
`domain discrete` discipline is accepted; `domain discrete` +
`potential Voltage;` is rejected with the named diagnostic (was silent); a
discrete net in an analog access stays a clean error.
