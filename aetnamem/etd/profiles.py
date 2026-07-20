"""Versioned Evidence-to-Decision profiles.

These templates support EtD-shaped workflows.  They do not assert GRADE,
clinical, or regulatory compliance; organizations remain responsible for
their methods, criteria selection, and judgments.
"""

from __future__ import annotations

from aetnamem.decisions import CriterionSpec, DecisionTemplate


YES_SCALE = ("no", "probably_no", "probably_yes", "yes", "varies", "do_not_know")
MAGNITUDE_SCALE = ("trivial", "small", "moderate", "large", "varies", "do_not_know")
CERTAINTY_SCALE = ("very_low", "low", "moderate", "high", "no_included_studies")
BALANCE_SCALE = (
    "favors_comparator",
    "probably_favors_comparator",
    "does_not_favor_either",
    "probably_favors_intervention",
    "favors_intervention",
    "varies",
    "do_not_know",
)


def clinical_etd_template() -> DecisionTemplate:
    """A population-perspective clinical recommendation template."""

    return DecisionTemplate(
        template_id="clinical-etd",
        version="1.0.0",
        title="Clinical Evidence-to-Decision",
        profile="etd",
        criteria=(
            CriterionSpec("problem_priority", "Is the problem a priority?", YES_SCALE),
            CriterionSpec("desirable_effects", "How substantial are the desirable effects?", MAGNITUDE_SCALE, rating_schemes=("grade-certainty",)),
            CriterionSpec("undesirable_effects", "How substantial are the undesirable effects?", MAGNITUDE_SCALE, rating_schemes=("grade-certainty",)),
            CriterionSpec("certainty", "What is the overall certainty of evidence?", CERTAINTY_SCALE, rating_schemes=("grade-certainty",)),
            CriterionSpec("values", "Is there important uncertainty or variability in values?", YES_SCALE),
            CriterionSpec("balance", "Does the balance favor the intervention or comparator?", BALANCE_SCALE),
            CriterionSpec("resources", "Are resource requirements acceptable?", YES_SCALE),
            CriterionSpec("cost_effectiveness", "Does cost-effectiveness favor the intervention?", YES_SCALE, required=False),
            CriterionSpec("equity", "What is the impact on equity?", ("reduced", "probably_reduced", "unchanged", "probably_increased", "increased", "varies", "do_not_know")),
            CriterionSpec("acceptability", "Is the intervention acceptable to key stakeholders?", YES_SCALE),
            CriterionSpec("feasibility", "Is the intervention feasible to implement?", YES_SCALE),
        ),
        sections=(
            "question",
            "population",
            "intervention",
            "comparator",
            "outcomes",
            "subgroups",
            "implementation",
            "monitoring",
            "research_priorities",
        ),
        metadata={
            "methodology_boundary": "Supports an EtD-shaped process; does not certify GRADE compliance.",
            "perspective": "population",
        },
    )


def generic_etd_template() -> DecisionTemplate:
    """Domain-neutral EtD template for policy and business decisions."""

    return DecisionTemplate(
        template_id="generic-etd",
        version="1.0.0",
        title="Generic Evidence-to-Decision",
        profile="etd",
        criteria=(
            CriterionSpec("problem_priority", "Is the problem a priority?", YES_SCALE),
            CriterionSpec("benefits", "How substantial are the expected benefits?", MAGNITUDE_SCALE),
            CriterionSpec("harms", "How substantial are the expected harms?", MAGNITUDE_SCALE),
            CriterionSpec("evidence_certainty", "How certain is the evidence?", CERTAINTY_SCALE, rating_schemes=("grade-certainty", "organization-certainty")),
            CriterionSpec("cost", "Are resource requirements acceptable?", YES_SCALE),
            CriterionSpec("equity", "Will the option improve equitable outcomes?", YES_SCALE),
            CriterionSpec("acceptability", "Is the option acceptable?", YES_SCALE),
            CriterionSpec("feasibility", "Is the option feasible?", YES_SCALE),
        ),
        sections=("question", "context", "alternatives", "outcomes", "implementation", "monitoring"),
        metadata={"methodology_boundary": "Host-defined EtD workflow; not a clinical recommendation method."},
    )

