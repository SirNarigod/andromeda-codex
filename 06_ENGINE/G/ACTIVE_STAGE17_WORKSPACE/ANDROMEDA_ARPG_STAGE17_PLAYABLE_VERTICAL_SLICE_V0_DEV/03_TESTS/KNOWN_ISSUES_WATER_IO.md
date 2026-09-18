# Known issue: water I/O precision tests

Status: deferred, non-blocking.

The historical `test_09` and `test_11` water precision checks compare state after a real save/reload on disk with a tolerance near `0.00001 s`. They can differ by approximately `0.07–0.12 s` due to filesystem and process scheduling latency, even on an idle machine. The failure is therefore classified as an overly strict timing assertion, not a tick-engine regression.

Scope excluded for now: changing water simulation, changing persistence semantics, or weakening the assertion. Recommended follow-up: replace wall-clock equality with deterministic simulation time or a tolerance appropriate to disk I/O, then rerun the dedicated water regression.