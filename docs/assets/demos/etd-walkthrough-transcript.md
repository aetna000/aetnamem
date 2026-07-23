# aetnamem evidence-to-decision walkthrough -- transcript

## intro

**Narration:** This is the same aetnamem control plane, applied to a structured decision instead of a single action: an evidence-to-decision workflow for a hospital panel deciding whether to change how it discharges patients.

**On screen:**

```
AETNAMEM EVIDENCE-TO-DECISION WORKFLOW ================
Namespace: demo-f0fb265d
Principals: dr-chair (chair), consumer-representative (voter),
            hospital-executive (approver)

```

## s1

**Narration:** Step one -- the chair opens a case on a clinical evidence-to-decision template. Not a free-form chat: a structured record. The question, the population, the intervention, and the comparator, captured up front.

**On screen:**

```
[1] Chair opens a case on the clinical EtD template.
✓ case dec_e3c9407d7509493091d5db55c6459630 created

```

## s2

**Narration:** Step two -- the chair seats the panel. A voting consumer representative, and a hospital executive who will later approve resourcing. Each principal is scoped to this one case.

**On screen:**

```
[2] Chair seats the panel: a voter and an institutional approver.
✓ panel seated: chair, voter, approver

```

## s3

**Narration:** Step three -- an evidence bundle is submitted, carrying its own trust tier and certainty rating. Certainty is a judgment about the evidence itself, tracked separately from how much the system trusts who submitted it.

**On screen:**

```
[3] Evidence bundle submitted, with its own trust tier and certainty rating.
✓ evidence revision drv_86c833975d074ac4826a98bbdfba5645 (certainty: moderate)

```

## s4

**Narration:** Step four -- the chair records a feasibility judgment, explicitly linked to that evidence. Every judgment has to point at what it's based on.

**On screen:**

```
[4] Chair records a feasibility judgment, linked to that evidence.
✓ assessment revision drv_87e6c56ed99a4acfa55ebdda147a01b5 -> supports evidence

```

## s5

**Narration:** Step five -- a recommendation is drafted, linked to the assessment that supports it. You can trace this recommendation back through the judgment, to the evidence, to its source.

**On screen:**

```
[5] Recommendation drafted, linked to the assessment that supports it.
✓ recommendation revision drv_0e835098905048cfb8595286a7899fa8

```

## s6

**Narration:** Step six -- the chair opens a ballot on the recommendation. Its visibility is hidden until close: nobody can see how anyone else voted while voting is still open.

**On screen:**

```
[6] Chair opens a hidden-until-close ballot on the recommendation.
✓ ballot bal_84b8804f31394576a6bba96d5627698b open (visibility: hidden_until_close)

```

## s7

**Narration:** Step seven -- the chair and the voter cast independent votes, neither one influenced by seeing the other's choice first.

**On screen:**

```
[7] Chair and voter cast independent votes. Neither sees the other's yet.
✓ 2 votes cast, both hidden until close

```

## s8

**Narration:** Step eight -- the ballot closes, and the outcome is computed deterministically, from a policy that was fixed before anyone voted.

**On screen:**

```
[8] Ballot closes. Outcome is computed deterministically from the policy.
✓ outcome out_78a8e8603be64f4aaf3da6d1a86ccb3e: passed

```

## s9

**Narration:** Step nine -- the chair adopts the recommendation, on the strength of that outcome. Adoption is its own recorded transition, not just implied by the vote.

**On screen:**

```
[9] Chair adopts the recommendation on the strength of that outcome.
✓ adoption adp_488f9918b8574812b39e00b064c8b37d

```

## s10

**Narration:** Step ten -- an implementation plan is drafted, linked to the adopted recommendation. This is where the decision starts turning into an actual change.

**On screen:**

```
[10] Implementation plan drafted, linked to the adopted recommendation.
✓ plan revision drv_d01117cd92f14c5597e42ae4dd487c6f

```

## s11

**Narration:** Step eleven -- the institutional approver signs off on resourcing the plan. This approval is a separate, distinct transition from the panel's own vote.

**On screen:**

```
[11] Institutional approver signs off on resourcing the plan.
✓ approval apr_e510c3d023394c25a6e6dbf29f90edf6 (approver: hospital-executive)

```

## s12

**Narration:** Step twelve -- and this is the important one -- the chair grants a scoped authorization. Not a blanket go-ahead: an exact adapter, an exact operation, an exact resource. This authorization, not the panel vote itself, is what a guarded action engine will revalidate before it stages or executes anything.

**On screen:**

```
[12] Chair grants a SCOPED authorization -- exact adapter, operation, resource.
✓ authorization aut_692e4c8c2e7a439ea2bfce61ddfcd43e scoped to filesystem.write_text on approved-change.md
This authorization -- not the panel vote itself -- is what a guarded
action engine will revalidate before it will stage or execute anything.

```

## s13

**Narration:** Step thirteen -- the chair exports the entire case as a canonical, hash-linked bundle. Every judgment, vote, adoption, approval, and authorization, traceable end to end.

**On screen:**

```
[13] Chair exports the full case as a canonical, hash-linked bundle.
✓ bundle exported: 4 linked record(s)

================ 
```

## done

**Narration:** Recommendation, institutional approval, and change authorization stayed three separate, auditable transitions the entire time. That separation is the point.

**On screen:**

```
DONE ================
Every judgment, vote, adoption, approval, and authorization above is
its own auditable transition -- recommendation, institutional approval,
and change authorization are kept distinct, on purpose.
```
