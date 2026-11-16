"""Throwaway Postgres cluster with a Supabase shim + the real migrations applied."""

import json
import os
import shutil
import socket
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from psycopg.types.string import TextLoader

psycopg.adapters.register_loader("uuid", TextLoader)  # uuids come back as str in tests

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
SHIM = Path(__file__).parent / "supabase_shim.sql"
JWT_SECRET = "test-secret-test-secret-test-secret-32b"


def _pg_bin(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for base in ("/opt/homebrew/opt/postgresql@16/bin", "/usr/lib/postgresql/16/bin"):
        p = Path(base) / name
        if p.exists():
            return str(p)
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def dsn():
    initdb, pg_ctl = _pg_bin("initdb"), _pg_bin("pg_ctl")
    if not (initdb and pg_ctl):
        pytest.skip("PostgreSQL binaries not found")
    tmp = tempfile.mkdtemp(prefix="cpm-pg-")
    os.environ["LC_ALL"] = (
        "en_US.UTF-8"  # postgres on macOS refuses to start without a valid locale
    )
    port = _free_port()
    subprocess.run(
        [initdb, "-D", f"{tmp}/data", "-U", "postgres", "--auth=trust", "-E", "UTF8"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            pg_ctl,
            "-D",
            f"{tmp}/data",
            "-o",
            f"-p {port} -c unix_socket_directories= -c listen_addresses=127.0.0.1",
            "-l",
            f"{tmp}/log",
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    url = f"postgresql://postgres@127.0.0.1:{port}/postgres"
    try:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(SHIM.read_text())
            for m in MIGRATIONS:
                c.execute(m.read_text())
        yield url
    finally:
        subprocess.run(
            [pg_ctl, "-D", f"{tmp}/data", "-m", "immediate", "stop"], capture_output=True
        )
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(autouse=True)
def _env(dsn, monkeypatch):
    from cpm.core.config import get_settings

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def admin_conn(dsn):
    """Superuser connection (bypasses RLS) for arranging test data. Truncates on teardown."""
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c
        c.execute("truncate auth.users, storage.objects, public.projects cascade")


class World:
    """Admin, clients ca (on A) / cb (on B) / unassigned. Each project has 2 packages (60/40), a
    published video+report and a draft video+report with analysis, observations and frames."""

    def __init__(self, c: psycopg.Connection):
        self.c = c
        self.admin = self.user("admin@x.test", promote=True)
        self.ca = self.user("ca@x.test")
        self.cb = self.user("cb@x.test")
        self.unassigned = self.user("none@x.test")
        self.A = self.project("A", self.ca)
        self.B = self.project("B", self.cb)

    def user(self, email, promote=False, meta=None):
        uid = str(uuid.uuid4())
        self.c.execute(
            "insert into auth.users (id,email,raw_user_meta_data) values (%s,%s,%s)",
            (uid, email, json.dumps(meta or {})),
        )
        if promote:
            self.c.execute("update public.profiles set role='admin' where id=%s", (uid,))
        return uid

    def project(self, name, client):
        c = self.c
        pid = c.execute(
            "insert into public.projects (name, created_by) values (%s,%s) returning id",
            (name, self.admin),
        ).fetchone()[0]
        p = {"id": pid, "name": name}
        with c.transaction():
            p["wp1"] = c.execute(
                "insert into public.work_packages (project_id,name,weight_percentage,"
                "initial_approved_percentage) values (%s,'Foundation',60,50) returning id",
                (pid,),
            ).fetchone()[0]
            p["wp2"] = c.execute(
                "insert into public.work_packages (project_id,name,weight_percentage,"
                "initial_approved_percentage) values (%s,'Roof',40,0) returning id",
                (pid,),
            ).fetchone()[0]
        c.execute(
            "insert into public.project_members (project_id,user_id) values (%s,%s)", (pid, client)
        )
        for label, published in (("pub", True), ("draft", False)):
            path = f"{pid}/{label}.mp4"
            v = c.execute(
                "insert into public.drone_videos (project_id,storage_path,original_filename,"
                "capture_date,status) values (%s,%s,%s,%s,'analyzed') returning id",
                (pid, path, f"{label}.mp4", "2026-01-01" if published else "2026-01-02"),
            ).fetchone()[0]
            p[f"video_{label}"], p[f"path_{label}"] = v, path
            fp, tp = f"{pid}/{v}/0000.jpg", f"{pid}/{v}/0000_t.jpg"
            f = c.execute(
                "insert into public.video_frames (video_id,frame_index,timestamp_seconds,"
                "storage_path,thumbnail_path,image_hash) values (%s,0,5,%s,%s,'h') returning id",
                (v, fp, tp),
            ).fetchone()[0]
            p[f"frame_{label}"], p[f"fpath_{label}"] = f, fp
            for b, n in (("drone-videos", path), ("video-frames", fp), ("video-frames", tp)):
                c.execute("insert into storage.objects (bucket_id,name) values (%s,%s)", (b, n))
            a = c.execute(
                "insert into public.ai_analyses (video_id,project_id,model_name,prompt_version,"
                "input_fingerprint,status) values (%s,%s,'m','v1','fp','completed') returning id",
                (v, pid),
            ).fetchone()[0]
            p[f"analysis_{label}"] = a
            ev = json.dumps([{"frame_id": f, "frame_index": 0, "timestamp_seconds": 5}])
            p[f"obs_{label}"] = c.execute(
                "insert into public.ai_observations (analysis_id,project_id,title,description,observation_type,"
                "confidence,evidence_frames,review_status,ai_original) values (%s,%s,'t','d','ongoing',0.8,"
                "%s,'approved','{}') returning id",
                (a, pid, ev),
            ).fetchone()[0]
            snap = json.dumps([{"work_package_id": p["wp1"], "approved_percentage": 50}])
            if published:
                p["report_pub"] = c.execute(
                    "insert into public.progress_reports (project_id,video_id,analysis_id,status,"
                    "overall_progress_percentage,assessment_coverage_percentage,summary,"
                    "package_progress_snapshot,published_by,published_at) values "
                    "(%s,%s,%s,'published',30,60,'s',%s,%s,now()) returning id",
                    (pid, v, a, snap, self.admin),
                ).fetchone()[0]
            else:
                p["report_draft"] = c.execute(
                    "insert into public.progress_reports (project_id,video_id,analysis_id,package_progress_snapshot)"
                    " values (%s,%s,%s,%s) returning id",
                    (pid, v, a, snap),
                ).fetchone()[0]
        c.execute(
            "insert into public.video_processing_jobs (video_id) values (%s)", (p["video_draft"],)
        )
        return p


@pytest.fixture
def world(admin_conn) -> World:
    return World(admin_conn)


@contextmanager
def as_user(
    dsn: str, uid: str | None, extra_claims: dict | None = None, role: str = "authenticated"
):
    """Run SQL exactly as PostgREST would: SET ROLE + JWT claims. Rolls back at the end."""
    with psycopg.connect(dsn) as conn, conn.transaction(force_rollback=True):
        claims = {"role": role, **({"sub": uid} if uid else {}), **(extra_claims or {})}
        conn.execute(f"set local role {role}")
        conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))
        yield conn


@pytest.fixture
def as_(dsn):
    def _as(uid, **kw):
        return as_user(dsn, uid, **kw)

    return _as
