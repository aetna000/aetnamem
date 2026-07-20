# Evidence-to-Decision profile

Status: **experimental**  
Profile version: `clinical-etd@1.0.0`, `generic-etd@1.0.0`  
Implemented surface: Python SDK and Markdown report

`aetnamem.etd` supplies versioned templates and reporting on top of the
generic [decision workflow](decision-workflow-spec.md). It supports structured,
transparent EtD processes; it does not automatically assess evidence or
produce recommendations.

## Clinical template

`clinical_etd_template()` includes problem priority, desirable and undesirable
effects, certainty, values, balance, resources, cost-effectiveness, equity,
acceptability, and feasibility. Case sections cover the question, population,
intervention, comparator, outcomes, subgroups, implementation, monitoring, and
research priorities.

Criterion definitions and choices are data, not hard-coded engine branches.
Organizations may create their own immutable `DecisionTemplate`; every case
pins the selected definition and digest so later template changes cannot
rewrite a historic decision.

## Recommended artifact chain

```text
evidence item/bundle
    -> synthesis
    -> criterion assessments
    -> recommendation revision
    -> ballot outcome
    -> adoption
    -> implementation plan
    -> institutional approvals
    -> scoped authorization
    -> optional guarded action and receipt
```

Evidence content may live in AetnaMem Memory, a document repository, a FHIR
server, or another host system. The formal decision record stores exact
revision IDs/digests and semantic links. A missing or retracted source should
be reported as unavailable or changed; it must not silently rewrite the
historical recommendation.

## Python example

```python
from aetnamem.decisions import ActorContext, DecisionEngine
from aetnamem.etd import clinical_etd_template

engine = DecisionEngine("organization.db")
chair = ActorContext("hospital-7", "principal-42")  # derived by the host
case = engine.create_case(
    chair,
    title="Discharge medication reconciliation",
    template=clinical_etd_template(),
    content={"question": "Should we introduce pharmacist reconciliation?"},
    idempotency_key="request-001",
)
```

See the [EtD playground](../examples/etd-playground/README.md) for the complete
multi-principal chain. It can run on SQLite or a real PostgreSQL server. The
[pilot and external-review runbook](etd-pilot-methodology-review.md) defines
the controls, acceptance evidence, and reviewer package for an organization
moving beyond synthetic data.

## Claims boundary

Safe claim:

> AetnaMem provides configurable, evidence-linked workflow primitives for
> implementing transparent EtD processes and tracing an adopted recommendation
> into an authorized, verified change.

The project does not claim GRADE compliance, clinical validation, regulatory
compliance, automatic certainty assessment, or automated clinical
recommendations. A real guideline group remains responsible for its methods,
panel composition, conflicts, judgments, and published recommendation.
