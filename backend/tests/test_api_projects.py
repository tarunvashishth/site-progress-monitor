import time

import jwt
import pytest
from conftest import JWT_SECRET
from fastapi.testclient import TestClient

from cpm.api.main import app

client = TestClient(app)


def tok(uid, **extra):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {"sub": uid, "aud": "authenticated", "exp": int(time.time()) + 600, **extra},
            JWT_SECRET,
            "HS256",
        )
    }


PKGS = [
    {"name": "Foundation", "weight_percentage": 60, "initial_approved_percentage": 50},
    {"name": "Roof", "weight_percentage": 40, "initial_approved_percentage": 0},
]


def test_auth_required_and_bad_tokens(world):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    bad = jwt.encode(
        {"sub": world.admin, "aud": "authenticated", "exp": int(time.time()) + 60},
        "wrong-secret-wrong-secret-wrong!!",
        "HS256",
    )
    assert client.get("/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401
    expired = tok(world.admin, exp=int(time.time()) - 5)
    assert client.get("/me", headers=expired).status_code == 401


def test_role_comes_from_db_not_token(world):
    h = tok(world.ca, role="admin", user_metadata={"role": "admin"}, app_metadata={"role": "admin"})
    assert client.get("/me", headers=h).json()["role"] == "client"
    assert (
        client.post("/projects", json={"name": "x", "work_packages": PKGS}, headers=h).status_code
        == 403
    )
    assert client.get("/me", headers=tok(world.admin)).json()["role"] == "admin"


def test_admin_creates_project_with_weighted_packages(world):
    r = client.post(
        "/projects", json={"name": "Tower", "work_packages": PKGS}, headers=tok(world.admin)
    )
    assert r.status_code == 201, r.text
    assert r.json()["overall_progress"] == 30.0  # 60*50% + 40*0%


@pytest.mark.parametrize(
    "pkgs",
    [
        [{"name": "A", "weight_percentage": 60, "initial_approved_percentage": 0}],
        [
            {"name": "A", "weight_percentage": 50, "initial_approved_percentage": 0},
            {"name": "A", "weight_percentage": 50, "initial_approved_percentage": 0},
        ],
        [{"name": "A", "weight_percentage": 100, "initial_approved_percentage": 101}],
        [{"name": "A", "weight_percentage": 100}],  # baseline is mandatory
        [],
    ],
)
def test_invalid_package_configs_rejected(world, pkgs):
    r = client.post(
        "/projects", json={"name": "T", "work_packages": pkgs}, headers=tok(world.admin)
    )
    assert r.status_code == 422


def test_sync_packages_enforces_total_and_is_atomic(world):
    h, pid = tok(world.admin), world.A["id"]
    cur = client.get(f"/projects/{pid}", headers=h).json()["work_packages"]
    ids = [w["work_package_id"] for w in cur]
    bad = {
        "work_packages": [
            {
                "id": ids[0],
                "name": "Foundation",
                "weight_percentage": 70,
                "initial_approved_percentage": 50,
            },
            {
                "id": ids[1],
                "name": "Roof",
                "weight_percentage": 40,
                "initial_approved_percentage": 0,
            },
        ]
    }
    assert client.post(f"/projects/{pid}/work-packages", json=bad, headers=h).status_code == 422
    good = {
        "work_packages": [
            {
                "id": ids[0],
                "name": "Foundation",
                "weight_percentage": 70,
                "initial_approved_percentage": 50,
            },
            {
                "id": ids[1],
                "name": "Roof",
                "weight_percentage": 30,
                "initial_approved_percentage": 0,
            },
        ]
    }
    r = client.post(f"/projects/{pid}/work-packages", json=good, headers=h)
    assert r.status_code == 200, r.text


def test_client_isolation(world):
    ha = tok(world.ca)
    ids = {p["id"] for p in client.get("/projects", headers=ha).json()["items"]}
    assert ids == {world.A["id"]}
    assert client.get(f"/projects/{world.A['id']}", headers=ha).status_code == 200
    assert client.get(f"/projects/{world.B['id']}", headers=ha).status_code == 404
    assert (
        client.patch(f"/projects/{world.A['id']}", json={"name": "x"}, headers=ha).status_code
        == 403
    )
    assert client.get("/dashboard", headers=ha).status_code == 403
    assert client.get("/clients", headers=ha).status_code == 403


def test_client_sees_published_progress_only(world):
    d = client.get(f"/projects/{world.A['id']}", headers=tok(world.ca)).json()
    assert d["latest_report"]["id"] == world.A["report_pub"]
    assert d["overall_progress"] == 30.0 and len(d["history"]) == 1


def test_membership_management(world):
    h = tok(world.admin)
    r = client.post(f"/projects/{world.A['id']}/members", json={"email": "cb@x.test"}, headers=h)
    assert r.status_code == 201
    assert (
        client.post(
            f"/projects/{world.A['id']}/members", json={"email": "admin@x.test"}, headers=h
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/projects/{world.A['id']}/members", json={"email": "nobody@x.test"}, headers=h
        ).status_code
        == 404
    )
    assert {p["id"] for p in client.get("/projects", headers=tok(world.cb)).json()["items"]} == {
        world.A["id"],
        world.B["id"],
    }


def test_dashboard_counts(world):
    d = client.get("/dashboard", headers=tok(world.admin)).json()
    assert d["total_projects"] == 2 and d["reports_awaiting_review"] == 2
