"""Extra offline test: the executive summary is regenerated when reflection revises the draft."""
from fastapi.testclient import TestClient

from app import config, llm, main
from tests.test_agent import REQUEST, REVIEW, make_fake


def test_summary_regenerated_after_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    labels = []
    fake = make_fake(review=REVIEW)

    def spy(system, user, *, max_tokens=1500, label="llm"):
        labels.append(label)
        return fake(system, user, max_tokens=max_tokens, label=label)

    monkeypatch.setattr(llm, "chat_json", spy)
    body = TestClient(main.app).post("/agent", json=REQUEST).json()
    assert body["reflection"]["verdict"] == "revised"
    assert labels.count("summary") == 2


def test_summary_not_regenerated_when_review_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    labels = []
    fake = make_fake()

    def spy(system, user, *, max_tokens=1500, label="llm"):
        labels.append(label)
        return fake(system, user, max_tokens=max_tokens, label=label)

    monkeypatch.setattr(llm, "chat_json", spy)
    TestClient(main.app).post("/agent", json=REQUEST)
    assert labels.count("summary") == 1
