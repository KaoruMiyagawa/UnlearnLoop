"""Idempotent content pack importer for VerbaTrail Stage 2.

Loads structured JSON learning content packs into the subject-agnostic schema
without duplicating records or overwriting learner progress.
"""

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import QuestionRole, QuestionType
from app.domain.exams import domain_for_variant
from app.domain.exceptions import DomainRuleViolationError
from app.persistence.models import (
    KnowledgeTopic,
    KnowledgeTopicDependency,
    LearningMaterial,
    Question,
    ReadingGroupVersion,
)
from app.persistence.reading_groups import import_matching_headings

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_PYTHON_PACK_PATH = BACKEND_DIR / "content" / "python_basics_pack.json"


@dataclass(frozen=True)
class SeedSummary:
    """Summary of an idempotent content pack import run."""

    pack_id: str
    domain_code: str
    topics_created: int
    topics_updated: int
    dependencies_created: int
    materials_created: int
    materials_updated: int
    questions_created: int
    questions_updated: int


def validate_python_snippet_syntax(snippet: str, *, context_id: str) -> None:
    """Verify that a Python content pack snippet is valid Python 3 syntax."""
    try:
        ast.parse(snippet)
    except SyntaxError as exc:
        raise DomainRuleViolationError(
            f"Invalid Python 3 syntax in content item '{context_id}': {exc}"
        ) from exc


def load_content_pack_file(path: Path | None = None) -> dict[str, Any]:
    """Read and parse a JSON content pack from disk."""
    target_path = path or DEFAULT_PYTHON_PACK_PATH
    with target_path.open("r", encoding="utf-8") as fp:
        data: dict[str, Any] = json.load(fp)
    return data


def load_matching_headings_diagnostic_pack(session: Session) -> dict[str, Any]:
    """Publish a new private-rule revision of the original initial groups."""
    content_dir = BACKEND_DIR / "app" / "content"
    pack = load_content_pack_file(content_dir / "ielts_matching_headings_pack.json")
    additions = load_content_pack_file(content_dir / "ielts_matching_headings_diagnostics.json")
    for topic in pack["topics"]:
        tasks = additions["questions"][topic["id"]]
        task_versions = {
            task["id"]: import_matching_headings(session, **task["reading_group"]).id
            for task in tasks
        }
        for question in topic["questions"]:
            rules = question["reading_group"]["private_rules"]
            rules["rules_version"] = "2"
            rules["diagnostics"] = {**additions["initial"][question["id"]], "task_versions": task_versions}
        topic["questions"].extend(tasks)
    return pack


def import_content_pack(
    session: Session,
    pack_data: dict[str, Any] | None = None,
    *,
    pack_path: Path | None = None,
) -> SeedSummary:
    """Idempotently import a structured content pack into the database session.

    Repeated runs update static topic/material/question metadata in place by stable ID/slug
    without deleting or corrupting existing learner sessions, attempts, or evidence.
    """
    payload = pack_data if pack_data is not None else load_content_pack_file(pack_path)
    pack_id = str(payload["pack_id"])
    domain_code = str(payload["domain_code"])
    topics_data: list[dict[str, Any]] = payload.get("topics", [])

    topics_created = 0
    topics_updated = 0
    dependencies_created = 0
    materials_created = 0
    materials_updated = 0
    questions_created = 0
    questions_updated = 0

    slug_to_topic: dict[str, KnowledgeTopic] = {}

    # Pass 1: Upsert KnowledgeTopics
    for t_item in topics_data:
        topic_id = str(t_item["id"])
        slug = str(t_item["slug"])
        t_domain = str(t_item.get("domain_code", domain_code))

        existing_topic = session.get(KnowledgeTopic, topic_id)
        if existing_topic is None:
            existing_topic = session.scalar(
                select(KnowledgeTopic).where(KnowledgeTopic.slug == slug)
            )

        if existing_topic is None:
            topic = KnowledgeTopic(
                id=topic_id,
                slug=slug,
                domain_code=t_domain,
                title=str(t_item["title"]),
                summary=str(t_item["summary"]),
                difficulty_level=int(t_item.get("difficulty_level", 1)),
                common_error_patterns=list(t_item.get("common_error_patterns", [])),
            )
            session.add(topic)
            topics_created += 1
        else:
            topic = existing_topic
            topic.slug = slug
            topic.domain_code = t_domain
            topic.title = str(t_item["title"])
            topic.summary = str(t_item["summary"])
            topic.difficulty_level = int(t_item.get("difficulty_level", 1))
            topic.common_error_patterns = list(
                t_item.get("common_error_patterns", [])
            )
            topics_updated += 1

        session.flush()
        slug_to_topic[slug] = topic

        # Upsert LearningMaterials for this topic
        for m_item in t_item.get("materials", []):
            mat_id = str(m_item["id"])
            existing_mat = session.get(LearningMaterial, mat_id)
            if existing_mat is None:
                mat = LearningMaterial(
                    id=mat_id,
                    topic_id=topic.id,
                    title=str(m_item["title"]),
                    summary=str(m_item["summary"]),
                    content_body=str(m_item["content_body"]),
                    content_format=str(m_item.get("content_format", "markdown")),
                    version=int(m_item.get("version", 1)),
                )
                session.add(mat)
                materials_created += 1
            else:
                existing_mat.topic_id = topic.id
                existing_mat.title = str(m_item["title"])
                existing_mat.summary = str(m_item["summary"])
                existing_mat.content_body = str(m_item["content_body"])
                existing_mat.content_format = str(
                    m_item.get("content_format", "markdown")
                )
                existing_mat.version = int(m_item.get("version", 1))
                materials_updated += 1

        session.flush()

        # Upsert Questions for this topic
        for q_item in t_item.get("questions", []):
            q_id = str(q_item["id"])
            role_enum = QuestionRole(str(q_item["question_role"]))
            type_enum = QuestionType(str(q_item["question_type"]))
            snippet = q_item.get("context_snippet")

            if t_domain == "python" and snippet:
                validate_python_snippet_syntax(str(snippet), context_id=q_id)

            existing_q = session.get(Question, q_id)
            group_version_id = None
            if type_enum == QuestionType.MATCHING_HEADINGS:
                group_data = q_item.get("reading_group")
                if not group_data or domain_for_variant(group_data["exam_variant"]) != t_domain:
                    raise DomainRuleViolationError("Matching Headings content must match its IELTS topic domain.")
                diagnostics = group_data["private_rules"].get("diagnostics")
                if diagnostics and diagnostics.get("role") != role_enum.value:
                    raise DomainRuleViolationError("Matching Headings diagnostic content must match its question role.")
                group = import_matching_headings(session, **group_data)
                group_version_id = group.id
                if existing_q and existing_q.reading_group_version_id:
                    previous = session.get(ReadingGroupVersion, existing_q.reading_group_version_id)
                    if previous.group_id != group.group_id or previous.exam_variant != group.exam_variant:
                        raise DomainRuleViolationError("A published question cannot be reassigned to a different reading group.")
            elif q_item.get("reading_group") or (existing_q and existing_q.reading_group_version_id):
                raise DomainRuleViolationError("Reading group content requires its published question type.")
            if existing_q is None:
                q_obj = Question(
                    id=q_id,
                    topic_id=topic.id,
                    material_id=q_item.get("material_id"),
                    parent_question_id=q_item.get("parent_question_id"),
                    question_role=role_enum.value,
                    question_type=type_enum.value,
                    reading_group_version_id=group_version_id,
                    prompt_text=str(q_item["prompt_text"]),
                    context_snippet=str(snippet) if snippet is not None else None,
                    standard_answer=str(q_item["standard_answer"]),
                    answer_explanation=str(q_item["answer_explanation"]),
                    evaluation_rubric=dict(q_item.get("evaluation_rubric", {})),
                    difficulty=int(q_item.get("difficulty", 1)),
                    version=int(q_item.get("version", 1)),
                )
                session.add(q_obj)
                questions_created += 1
            else:
                new_prompt = str(q_item["prompt_text"])
                new_snippet = str(snippet) if snippet is not None else None
                new_std_answer = str(q_item["standard_answer"])
                new_version = int(q_item.get("version", 1))

                content_changed = (
                    existing_q.prompt_text != new_prompt
                    or existing_q.context_snippet != new_snippet
                    or existing_q.standard_answer != new_std_answer
                )
                if content_changed and existing_q.attempts and new_version <= existing_q.version:
                    raise DomainRuleViolationError(
                        f"Question '{q_id}' has historical attempts at version {existing_q.version}; "
                        f"modifying question content requires incrementing version (got {new_version})."
                    )

                existing_q.topic_id = topic.id
                existing_q.material_id = q_item.get("material_id")
                existing_q.parent_question_id = q_item.get("parent_question_id")
                existing_q.question_role = role_enum.value
                existing_q.question_type = type_enum.value
                existing_q.reading_group_version_id = group_version_id
                existing_q.prompt_text = new_prompt
                existing_q.context_snippet = new_snippet
                existing_q.standard_answer = new_std_answer
                existing_q.answer_explanation = str(q_item["answer_explanation"])
                existing_q.evaluation_rubric = dict(
                    q_item.get("evaluation_rubric", {})
                )
                existing_q.difficulty = int(q_item.get("difficulty", 1))
                existing_q.version = new_version
                questions_updated += 1

        session.flush()

    # Pass 2: Upsert KnowledgeTopicDependency edges
    for t_item in topics_data:
        slug = str(t_item["slug"])
        topic = slug_to_topic[slug]
        for prereq_slug in t_item.get("prerequisites", []):
            prereq_topic = slug_to_topic.get(str(prereq_slug))
            if prereq_topic is None:
                prereq_topic = session.scalar(
                    select(KnowledgeTopic).where(
                        KnowledgeTopic.slug == str(prereq_slug)
                    )
                )
            if prereq_topic is None:
                raise DomainRuleViolationError(
                    f"Topic '{slug}' references unknown prerequisite slug '{prereq_slug}'."
                )

            existing_dep = session.scalar(
                select(KnowledgeTopicDependency).where(
                    KnowledgeTopicDependency.topic_id == topic.id,
                    KnowledgeTopicDependency.prerequisite_topic_id == prereq_topic.id,
                )
            )
            if existing_dep is None:
                session.add(
                    KnowledgeTopicDependency(
                        topic_id=topic.id,
                        prerequisite_topic_id=prereq_topic.id,
                    )
                )
                dependencies_created += 1

    session.flush()

    return SeedSummary(
        pack_id=pack_id,
        domain_code=domain_code,
        topics_created=topics_created,
        topics_updated=topics_updated,
        dependencies_created=dependencies_created,
        materials_created=materials_created,
        materials_updated=materials_updated,
        questions_created=questions_created,
        questions_updated=questions_updated,
    )
