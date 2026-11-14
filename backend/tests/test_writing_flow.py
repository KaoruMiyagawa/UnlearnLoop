from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.persistence.models import Attempt

BASE = "/api/v1/writing/sessions"


def open_session(client, learner="writer-a"):
    response = client.post(BASE, json={"learner_id": learner})
    assert response.status_code == 200, response.text
    return response.json()


def save(client, session, body, version, learner="writer-a"):
    return client.put(f"{BASE}/{session}/draft", params={"learner_id": learner},
                      json={"body": body, "version": version})


def submit(client, session, body, version, key, learner="writer-a"):
    return client.post(f"{BASE}/{session}/revisions", params={"learner_id": learner},
                       json={"body": body, "version": version, "idempotency_key": key})


def test_writing_round_trip(client, session_factory):
    opened = open_session(client)
    sid = opened["session_id"]
    assert opened["task"]["suggested_words"] == 250
    assert opened["task"]["version"] == "writing-shared-spaces-v1"
    first_text = "Gardens help neighbours.\n\nThey share space."
    saved = save(client, sid, first_text.replace("\n", "\r\n"), 0)
    assert saved.status_code == 200 and saved.json()["version"] == 1
    assert open_session(client)["draft"] == saved.json()
    assert save(client, sid, "stale", 0).status_code == 409
    assert submit(client, sid, "\t  \n", 1, "writing-empty").status_code == 422

    first = submit(client, sid, first_text, 1, "writing-first").json()
    assert first["number"] == 1 and first["source_revision_id"] is None
    assert first["feedback"]["paragraph_blocks"] == 2
    assert first["feedback"]["word_count"] == 6
    assert first["feedback"]["semantic_quality"] == "not_assessed"
    assert first["feedback"]["below_suggested_words"]
    assert submit(client, sid, first_text, 1, "writing-first").json() == first
    assert submit(client, sid, "changed", 1, "writing-first").status_code == 409
    assert submit(client, sid, first_text, 2, "different-key").status_code == 409

    later_text = first_text + "\n\nSports facilities help too."
    second = submit(client, sid, later_text, 2, "writing-second").json()
    assert second["source_revision_id"] == first["id"]
    assert second["feedback"]["word_count_change"] == 4
    assert open_session(client)["revisions"][0]["number"] == 2
    assert "body" not in open_session(client)["revisions"][0]
    first_url = f"{BASE}/{sid}/revisions/{first['id']}"
    assert client.get(first_url, params={"learner_id": "writer-a"}).json() == first
    assert client.get(first_url, params={"learner_id": "writer-b"}).status_code == 404
    assert open_session(client, "writer-b")["draft"]["body"] == ""
    assert save(client, sid, "wrong learner", 3, "writer-b").status_code == 404
    assert submit(client, sid, "wrong learner", 3, "writing-other", "writer-b").status_code == 404

    profile = client.get("/api/v1/profile/history", params={"learner_id": "writer-a", "limit": 1}).json()
    assert profile[0]["kind"] == "writing_submission" and profile[0]["session_id"] == sid
    assert profile[0]["attempt_id"] is None and later_text not in str(profile)
    assert client.get("/api/v1/profile/history", params={"learner_id": "writer-b"}).json() == []
    with session_factory() as db:
        assert db.scalars(select(Attempt).where(Attempt.session_id == sid)).all() == []
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE writing_revisions SET body='altered' WHERE id = :id"), {"id": first["id"]})
        db.rollback()
        with pytest.raises(IntegrityError):
            db.execute(text("DELETE FROM writing_revisions WHERE id = :id"), {"id": first["id"]})


def test_length_unicode_and_simultaneous_retry(client, session_factory):
    sid = open_session(client)["session_id"]
    body = "<script>document.body.remove()</script> Café doesn’t 🇬🇧\n\n" + ("word " * 3980)
    assert len(body) < 20000
    assert save(client, sid, body, 0).json()["body"] == body
    invalid = save(client, sid, "a" * 20001, 1)
    assert invalid.status_code == 422 and "a" * 100 not in invalid.text
    assert save(client, sid, "a\x00b", 1).status_code == 422
    malformed = client.put(f"{BASE}/{sid}/draft", params={"learner_id": "writer-a"},
                           content=json.dumps({"body": "a\ud800b", "version": 1}),
                           headers={"Content-Type": "application/json"})
    assert malformed.status_code == 422
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(client, sid, body, 1, "writing-parallel"), range(2)))
    assert all(result.status_code == 200 for result in results)
    assert results[0].json() == results[1].json()
    assert len(open_session(client)["revisions"]) == 1
