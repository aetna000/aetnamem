# Data provenance

`benchmark-results.csv` and `auditability.csv` are lossless tabular projections
of the public MemoryStackBench leaderboard files at commit:

```text
10b9407ce54c92bcb8aee24099505427aabeebcd
```

Source files and SHA-256 digests:

```text
site/leaderboard/leaderboard.json
54e47dbd204d3cb6b0c479193a8901005ef2ae96163fe433b4307c26168044cb

site/leaderboard/auditability.json
bbb1b1554d19e799b362e37df771ad39841ec34de3791228ac8f44184e724527
```

The aetnamem row was rerun on 2026-07-13 with the benchmark code above and
the current aetnamem checkout at commit
`0cd082c9cac14f35a66ff946395a31847322005d`. The rerun produced 33/33 checks,
5/5 scenarios, and 81/81 severity-weighted points. Its scorecard SHA-256 was:

```text
ef60b9b2676733871f24015cb6130a83a61c72b03475fc247012b245a8316e0b
```

The public benchmark and aetnamem repositories are maintained under the same
GitHub account. The paper therefore describes the result as reproducible
self-evaluation, not third-party validation. The standalone demo verifiers are
implementation-independent programs, not independent organizations.
