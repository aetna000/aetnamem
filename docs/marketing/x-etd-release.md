# X article — AetnaMem 0.4.0a1

## Post copy

We just released AetnaMem 0.4.0a1: an open, auditable path from evidence to an
approved change.

Most organizations do not struggle because they have zero evidence. The hard
part is what happens next:

- Which evidence informed each judgment?
- Who was eligible to vote—and who was recused?
- What exactly did the panel recommend?
- Who approved the implementation plan?
- What action was authorized?
- Did the system execute that exact authorized change?

Those handoffs are often spread across documents, meetings, ticketing systems,
and application logs. That makes decisions difficult to reproduce, challenge,
or audit.

AetnaMem now provides a generic Evidence-to-Decision (EtD) → recommendation →
approval → authorization → guarded implementation chain.

What shipped:

• Immutable, versioned evidence and decision artifacts  
• Exact evidence lineage instead of fuzzy “related document” links  
• Role-based panel membership, conflicts of interest, and recusal  
• Frozen voter eligibility and hidden-until-close ballots  
• Deterministic quorum and consensus outcomes  
• Separate recommendation adoption, institutional approval, and scoped change
authorization  
• PostgreSQL support for real multi-process hosts  
• Ed25519 and AWS KMS-compatible principal attestations and signed receipts  
• Retention policies and verifiable purge receipts for decision payloads and
sensitive COI details  
• A clinical/generic EtD profile, offline verifier, complete playground, and
pilot/methodology-review runbook

The architecture stays deliberately general. AetnaMem does not become your
login system, hospital portal, or AI provider. Your host authenticates users
and supplies the UI; the library supplies the decision contract, persistence,
concurrency, audit trail, signatures, and export verification. It works with
Claude, Grok/xAI, OpenAI, Ollama, conventional software, or no model at all.

Try the alpha:

```bash
pip install --pre 'aetnamem[production]==0.4.0a1'
aetnamem-etd-playground --db ./etd.db --output ./etd-output
aetnamem-etd-verify ./etd-output/decision-bundle.json
```

Why alpha? Because software can prove internal consistency, but it cannot
manufacture external clinical legitimacy. We have completed the engineering
and published the real pilot/reviewer protocol. A hospital or policy group
must still run the workflow with real participants, and an independent
methodologist must review the result.

That boundary matters. “Auditable EtD infrastructure” is a claim we can test.
“Clinically validated” or “GRADE compliant” requires separate evidence.

The release passed 173 tests, including simultaneous PostgreSQL voter
processes, vote-versus-close races, complete evidence-to-authorization flows,
signed receipt verification, purge verification, and clean package installs.

Repository: https://github.com/aetna000/aetnamem  
PyPI: https://pypi.org/project/aetnamem/0.4.0a1/

If you work on clinical guidelines, policy governance, or controlled business
change, I would especially value feedback on the host API and pilot protocol.

#OpenSource #ClinicalGovernance #EvidenceBasedMedicine #AIEngineering
#HealthTech #Python

## Short launch post

AetnaMem 0.4.0a1 is out: a provider-neutral, auditable chain from evidence →
EtD judgment → recommendation → approval → scoped authorization → guarded
change.

PostgreSQL multi-user support, signed Ed25519/KMS receipts, COI/retention purge,
offline verification, and a complete playground.

```bash
pip install --pre 'aetnamem[production]==0.4.0a1'
```

https://github.com/aetna000/aetnamem

#OpenSource #ClinicalGovernance #Python
