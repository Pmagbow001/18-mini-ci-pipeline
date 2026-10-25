from datetime import datetime, timezone

from app.models import Run
from app.seed import STEPS
from app.main import Trigger


def test_steps_are_ordered():
    assert [step["name"] for step in STEPS] == ["Lint", "Test", "Build"]


def test_default_fixture():
    assert Trigger().fixture == "success"


def test_api_initializes_database_and_allows_local_origins(client):
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        response = client.get("/api/health", headers={"Origin": origin})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers["access-control-allow-origin"] == origin

    assert client.get("/api/projects").json()[0]["slug"] == "sample-typescript"
    assert client.get("/api/pipelines").json()[0]["steps"] == STEPS
    assert client.get("/api/runs").json() == []


def test_trigger_validates_fixture_and_creates_ordered_jobs(client):
    pipeline_id = client.get("/api/pipelines").json()[0]["id"]
    created = client.post(f"/api/pipelines/{pipeline_id}/runs", json={})
    assert created.status_code == 201

    run = client.get(f"/api/runs/{created.json()['id']}").json()
    assert run["status"] == "queued"
    assert [job["name"] for job in run["jobs"]] == ["Lint", "Test", "Build"]
    assert all(job["status"] == "pending" for job in run["jobs"])

    invalid = client.post(
        f"/api/pipelines/{pipeline_id}/runs",
        json={"fixture": "arbitrary command"},
    )
    assert invalid.status_code == 422


def test_cancel_queued_run_cancels_pending_jobs(client):
    pipeline_id = client.get("/api/pipelines").json()[0]["id"]
    created = client.post(
        f"/api/pipelines/{pipeline_id}/runs",
        json={"fixture": "success"},
    )
    run_id = created.json()["id"]

    response = client.post(f"/api/runs/{run_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "cancelled"
    assert all(job["status"] == "cancelled" for job in run["jobs"])


def test_cancel_running_run_requests_worker_cancellation(client, database):
    pipeline_id = client.get("/api/pipelines").json()[0]["id"]
    run_id = client.post(
        f"/api/pipelines/{pipeline_id}/runs",
        json={"fixture": "success"},
    ).json()["id"]
    with database.begin() as db:
        run = db.get(Run, run_id)
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)

    response = client.post(f"/api/runs/{run_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["cancel_requested"] is True
