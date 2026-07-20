# EtD playground

This playground runs a complete, headless Evidence-to-Decision workflow with
three simulated host-authenticated principals: a chair, a voting consumer
representative, and an institutional approver.

It creates evidence and assessment revisions, opens a hidden-until-close
ballot, records two independently scoped votes, adopts the recommendation,
approves an implementation plan, and issues a scoped authorization. It then
exports a canonical JSON bundle and a Markdown report.

```bash
pip install aetnamem
aetnamem-etd-playground \
  --db ./playground.db \
  --output ./playground-output
```

For a real Linux/PostgreSQL process contract:

```bash
pip install aetnamem
DECISION_DATABASE_URL='postgresql://...' \
  aetnamem-etd-playground \
    --postgres-dsn-env DECISION_DATABASE_URL \
    --output ./playground-output
```

Each run uses a new namespace unless `--namespace` is supplied. The
playground demonstrates domain behavior, not authentication: a real FastAPI,
Django, Flask, or other host must derive `ActorContext` from its authenticated
request and must not accept namespace or principal identity from a client
payload.

The [pilot configuration example](pilot-config.example.json) and [pilot and
methodology-review runbook](../../docs/etd-pilot-methodology-review.md) define
the production-readiness evidence expected from a host. They do not claim an
external pilot has already occurred.
