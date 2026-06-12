from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowStep:
    name: str
    label: str
    track: str
    optional: bool = False
    skill_aliases: tuple[str, ...] = ()


WORKFLOW_STEPS = {
    "create": WorkflowStep("create", "create-story", "standard"),
    "dev": WorkflowStep("dev", "dev-story", "standard"),
    "auto": WorkflowStep("auto", "automate", "standard"),
    "review": WorkflowStep("review", "code-review", "standard"),
    "retro": WorkflowStep("retro", "retro", "standard", optional=True),
    "atdd": WorkflowStep("atdd", "atdd", "tea", skill_aliases=("bmad-testarch-atdd", "bmad-tea-testarch-atdd")),
    "test_automate": WorkflowStep(
        "test_automate",
        "test-automate",
        "tea",
        skill_aliases=("bmad-testarch-automate", "bmad-tea-testarch-automate"),
    ),
    "test_review": WorkflowStep(
        "test_review",
        "test-review",
        "tea",
        skill_aliases=("bmad-testarch-test-review", "bmad-tea-testarch-test-review"),
    ),
    "trace": WorkflowStep("trace", "trace", "tea", skill_aliases=("bmad-testarch-trace", "bmad-tea-testarch-trace")),
    "nfr": WorkflowStep("nfr", "nfr", "tea", optional=True, skill_aliases=("bmad-testarch-nfr", "bmad-tea-testarch-nfr")),
}

STANDARD_SEQUENCE = ["create", "dev", "auto", "review", "retro"]
TEA_CORE_SEQUENCE = ["create", "atdd", "dev", "test_automate", "test_review", "trace", "review"]
TEA_OPTIONAL_STEPS = {"nfr", "retro"}
TEA_QUALITY_STEPS = ["test_automate", "test_review", "nfr", "trace"]
TEA_TRACK_STEPS = {name for name, step in WORKFLOW_STEPS.items() if step.track == "tea"}
VALID_STEP_NAMES = set(WORKFLOW_STEPS)


def selected_optional_steps_from_sequence(sequence: list[str]) -> list[str]:
    return [step for step in ("nfr", "retro") if step in sequence]


def workflow_track_for_sequence(sequence: list[str]) -> str:
    return "tea" if any(step in TEA_TRACK_STEPS for step in sequence) else "standard"


def tea_steps_from_sequence(sequence: list[str]) -> list[str]:
    return [step for step in sequence if step in TEA_TRACK_STEPS]


def tea_summary_steps(sequence: list[str]) -> list[str]:
    return [WORKFLOW_STEPS[step].label for step in sequence if step in TEA_TRACK_STEPS]


def summary_steps_for_track(sequence: list[str], track: str) -> list[str]:
    return [WORKFLOW_STEPS[step].label for step in sequence if step in WORKFLOW_STEPS and WORKFLOW_STEPS[step].track == track]


def tea_skill_aliases(step: str) -> tuple[str, ...]:
    return WORKFLOW_STEPS.get(step, WorkflowStep(step, step, "unknown")).skill_aliases


def tea_required_steps(include_nfr: bool = False) -> list[str]:
    steps = ["atdd", "test_automate", "test_review", "trace"]
    if include_nfr:
        steps.append("nfr")
    return steps


def tea_sequence(*, include_nfr: bool, include_retro: bool) -> list[str]:
    sequence = list(TEA_CORE_SEQUENCE[:-2])
    if include_nfr:
        sequence.append("nfr")
    sequence.extend(TEA_CORE_SEQUENCE[-2:])
    if include_retro:
        sequence.append("retro")
    return sequence
