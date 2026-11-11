import pytest
from pydantic import ValidationError

from app.domain.reading_groups import HeadingAnswerKey, MatchingHeadingsGroup, evaluate_headings


@pytest.fixture
def group():
    return MatchingHeadingsGroup.model_validate({
        "id": "group", "section_id": "section", "display_schema_version": "1",
        "passage": {"id": "passage", "content_version": "1", "title": "Passage",
                    "paragraphs": [{"id": "a", "text": "First"}, {"id": "b", "text": "Second"}]},
        "options": [{"id": "i", "text": "One"}, {"id": "ii", "text": "Two"},
                    {"id": "iii", "text": "Distractor"}],
        "items": [{"id": "1", "paragraph_id": "a"}, {"id": "2", "paragraph_id": "b"}],
    })


@pytest.fixture
def key():
    return HeadingAnswerKey(rules_version="1", answers={"1": "i", "2": "ii"},
                            explanations={"1": "First", "2": "Second"})


@pytest.mark.parametrize(("answers", "outcome", "count"), [
    ({"1": "i", "2": "ii"}, "correct", 2),
    ({"1": "i", "2": "iii"}, "partial", 1),
    ({"1": "ii", "2": "i"}, "incorrect", 0),
])
def test_scoring(group, key, answers, outcome, count):
    result = evaluate_headings(group, key, answers)
    assert (result.outcome, result.correct_count) == (outcome, count)
    assert "answers" not in result.model_dump()
    assert "answers" not in group.model_dump()


@pytest.mark.parametrize("answers", [{}, {"1": "i"}, {"1": "i", "2": "i"},
                                    {"1": "i", "2": "unknown"}, {"1": "i", "2": "ii", "3": "iii"}])
def test_invalid_submission(group, key, answers):
    with pytest.raises(ValueError):
        evaluate_headings(group, key, answers)


def test_invalid_reference_is_rejected(group):
    data = group.model_dump()
    data["items"][0]["paragraph_id"] = "missing"
    with pytest.raises(ValidationError):
        MatchingHeadingsGroup.model_validate(data)
