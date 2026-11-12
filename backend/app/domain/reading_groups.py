"""Versioned reading group primitives; not yet connected to the learning API.

Public content and private scoring rules are separate types so callers must
explicitly choose which data can leave the server.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Paragraph(StrictModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class Passage(StrictModel):
    id: str = Field(min_length=1)
    content_version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    paragraphs: list[Paragraph] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_paragraphs(self):
        ids = [p.id for p in self.paragraphs]
        if len(ids) != len(set(ids)):
            raise ValueError("paragraph IDs must be unique")
        return self


class HeadingOption(StrictModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class HeadingItem(StrictModel):
    id: str = Field(min_length=1)
    paragraph_id: str = Field(min_length=1)


class MatchingHeadingsGroup(StrictModel):
    id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    display_schema_version: str = Field(min_length=1)
    question_type: Literal["matching_headings"] = "matching_headings"
    passage: Passage
    options: list[HeadingOption] = Field(min_length=1)
    items: list[HeadingItem] = Field(min_length=1)
    allow_reuse: bool = False

    @model_validator(mode="after")
    def valid_references(self):
        option_ids = [o.id for o in self.options]
        item_ids = [i.id for i in self.items]
        paragraph_ids = [i.paragraph_id for i in self.items]
        if len(option_ids) != len(set(option_ids)) or len(item_ids) != len(set(item_ids)):
            raise ValueError("option and item IDs must be unique")
        if len(paragraph_ids) != len(set(paragraph_ids)):
            raise ValueError("each paragraph may appear only once")
        if not set(paragraph_ids) <= {p.id for p in self.passage.paragraphs}:
            raise ValueError("item references an unknown paragraph")
        if not self.allow_reuse and len(option_ids) < len(item_ids):
            raise ValueError("not enough options for the no-reuse rule")
        return self


HeadingError = Literal["main_idea_vs_detail", "surface_keyword_matching"]
HeadingEvidenceRelation = Literal["supports", "contradicts", "neutral"]
MATCHING_HEADINGS_PROTOCOL = "matching-headings"
MATCHING_HEADINGS_DIAGNOSTIC_VERSION = "1"


class HeadingProbe(StrictModel):
    target: HeadingError
    relations: dict[str, HeadingEvidenceRelation]


class HeadingDiagnostics(StrictModel):
    protocol: str = Field(min_length=1)
    version: str = Field(min_length=1)
    source_group_id: str = Field(min_length=1)
    role: Literal["initial", "diagnostic_followup", "targeted_practice", "transfer_check", "review"]
    targets: list[HeadingError] = Field(min_length=1, max_length=2)
    task_versions: dict[str, str] = Field(default_factory=dict)
    distractors: dict[str, dict[str, list[HeadingError]]] = Field(default_factory=dict)
    probes: dict[str, HeadingProbe] = Field(default_factory=dict)

    def validate_for(self, group: MatchingHeadingsGroup, answers: dict[str, str]) -> None:
        items = {item.id for item in group.items}
        options = {option.id for option in group.options}
        targets = set(self.targets)
        if len(targets) != len(self.targets):
            raise ValueError("Diagnostic targets must be unique.")
        if self.role == "initial":
            if self.source_group_id != group.id or self.probes or not set(self.distractors) <= items:
                raise ValueError("Invalid initial diagnostic mapping.")
            for item_id, choices in self.distractors.items():
                for option, codes in choices.items():
                    if option not in options or option == answers[item_id] or not codes or not set(codes) <= targets:
                        raise ValueError("Invalid reviewed distractor mapping.")
        elif self.role == "diagnostic_followup":
            if self.task_versions or self.distractors or set(self.probes) != items or {probe.target for probe in self.probes.values()} != targets:
                raise ValueError("Each diagnostic item must probe an explicit target.")
            for item_id, probe in self.probes.items():
                if (
                    not set(probe.relations) <= options
                    or probe.relations.get(answers[item_id]) != "contradicts"
                    or "supports" not in probe.relations.values()
                ):
                    raise ValueError("Each probe must distinguish support from contrary evidence.")
        elif self.role in {"targeted_practice", "transfer_check", "review"}:
            if len(targets) != 1 or self.distractors or self.probes:
                raise ValueError("Intervention, transfer, and review tasks must target one cause.")
        elif len(targets) != 1 or self.distractors or self.probes or self.task_versions:
            raise ValueError("Practice must target one cause without diagnostic mappings.")


class HeadingAnswerKey(StrictModel):
    rules_version: str = Field(min_length=1)
    answers: dict[str, str]
    explanations: dict[str, str]
    diagnostics: HeadingDiagnostics | None = None


class HeadingResult(StrictModel):
    correct_by_item: dict[str, bool]
    correct_count: int
    total_count: int
    outcome: Literal["correct", "partial", "incorrect"]


def evaluate_headings(group: MatchingHeadingsGroup, key: HeadingAnswerKey,
                      answers: dict[str, str]) -> HeadingResult:
    """Evaluate a complete submission without returning the private key."""
    items = {item.id for item in group.items}
    options = {option.id for option in group.options}
    if set(key.answers) != items or set(key.explanations) != items:
        raise ValueError("answer key must cover every item")
    if not set(key.answers.values()) <= options:
        raise ValueError("answer key references an unknown option")
    if not group.allow_reuse and len(set(key.answers.values())) != len(items):
        raise ValueError("answer key violates the no-reuse rule")
    if set(answers) != items or not set(answers.values()) <= options:
        raise ValueError("submission must contain one valid option per item")
    if not group.allow_reuse and len(set(answers.values())) != len(items):
        raise ValueError("submission violates the no-reuse rule")
    results = {item.id: answers[item.id] == key.answers[item.id] for item in group.items}
    count = sum(results.values())
    return HeadingResult(correct_by_item=results, correct_count=count, total_count=len(items),
                         outcome="correct" if count == len(items) else "partial" if count else "incorrect")
