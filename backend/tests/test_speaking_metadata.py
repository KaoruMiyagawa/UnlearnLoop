from datetime import datetime, timezone


def test_metadata_history_idempotency_and_learner_filter(client, migrated_engine):
    prompts = client.get("/api/v1/speaking/prompts").json()
    assert len(prompts) == 3
    payload = {
        "learner_id": "speaking-test",
        "recording_id": "recording-test-123",
        "prompt_id": prompts[0]["id"],
        "prompt_version": prompts[0]["version"],
        "duration_seconds": 5.5,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "self_check": ["direct"],
    }
    first = client.post("/api/v1/speaking/practices", json=payload)
    assert first.status_code == 200
    assert first.json()["evaluation_status"] == "not_assessed"
    assert first.json()["evidence_type"] == "practice_only"
    assert client.post("/api/v1/speaking/practices", json=payload).json() == first.json()
    assert client.post("/api/v1/speaking/practices", json=payload | {"duration_seconds": 9}).status_code == 409
    assert client.post("/api/v1/speaking/practices", json=payload | {"audio": "unexpected"}).status_code == 422
    assert client.get("/api/v1/speaking/practices?learner_id=another").json() == []
    assert client.delete("/api/v1/speaking/practices/recording-test-123?learner_id=another").status_code == 404
    history = client.get("/api/v1/profile/history?learner_id=speaking-test").json()
    assert len(history) == 1 and history[0]["kind"] == "speaking_practice"
    assert client.delete("/api/v1/speaking/practices/recording-test-123?learner_id=speaking-test").status_code == 200
    assert client.get("/api/v1/profile/history?learner_id=speaking-test").json() == []
