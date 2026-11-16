"""Row Level Security, integrity triggers and job claiming against the real migrations."""

import psycopg
import pytest
from conftest import as_user


def ids(conn, sql, *args):
    return {str(r[0]) for r in conn.execute(sql, args).fetchall()}


def test_client_sees_only_assigned_project_data(world, as_):
    with as_(world.ca) as c:
        assert ids(c, "select id from public.projects") == {world.A["id"]}
        assert ids(c, "select id from public.work_packages") == {world.A["wp1"], world.A["wp2"]}
        assert ids(c, "select id from public.progress_reports") == {world.A["report_pub"]}
        assert ids(c, "select id from public.drone_videos") == {world.A["video_pub"]}
        assert ids(c, "select id from public.video_frames") == {world.A["frame_pub"]}


@pytest.mark.parametrize("table", ["ai_observations", "ai_analyses", "video_processing_jobs"])
def test_client_never_sees_draft_ai_or_jobs(world, as_, table):
    with as_(world.ca) as c:
        assert c.execute(f"select count(*) from public.{table}").fetchone()[0] == 0


def test_unassigned_client_sees_nothing(world, as_):
    with as_(world.unassigned) as c:
        for t in ("projects", "work_packages", "progress_reports", "drone_videos", "video_frames"):
            assert c.execute(f"select count(*) from public.{t}").fetchone()[0] == 0, t


def test_client_cannot_read_other_project_by_id(world, as_):
    with as_(world.ca) as c:
        for t, k in (
            ("projects", "id"),
            ("progress_reports", "project_id"),
            ("work_packages", "project_id"),
        ):
            assert (
                c.execute(
                    f"select count(*) from public.{t} where {k}=%s", (world.B["id"],)
                ).fetchone()[0]
                == 0
            )


def test_admin_sees_everything(world, as_):
    with as_(world.admin) as c:
        assert c.execute("select count(*) from public.projects").fetchone()[0] == 2
        assert c.execute("select count(*) from public.progress_reports").fetchone()[0] == 4
        assert c.execute("select count(*) from public.ai_observations").fetchone()[0] == 4


def test_anon_has_no_access(world, dsn):
    with as_user(dsn, None, role="anon") as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("select * from public.projects")


WRITES = [
    "insert into public.projects (name) values ('x')",
    "update public.projects set name='hacked'",
    "delete from public.projects",
    "insert into public.project_members (project_id,user_id) select id, '{ca}' from public.projects",
    "update public.work_packages set weight_percentage=1",
    "update public.progress_reports set summary='x'",
    "delete from public.progress_reports",
    "update public.drone_videos set status='failed'",
    "update public.ai_observations set review_status='rejected'",
]


@pytest.mark.parametrize("sql", WRITES)
def test_client_cannot_write(world, as_, sql):
    with as_(world.ca) as c:
        try:
            assert c.execute(sql.format(ca=world.ca)).rowcount in (0, -1)
        except psycopg.errors.InsufficientPrivilege:
            pass


def test_client_cannot_create_report(world, as_):
    with as_(world.ca) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(
                "insert into public.progress_reports (project_id,video_id,status,summary,"
                "overall_progress_percentage,assessment_coverage_percentage,published_by,published_at,"
                "package_progress_snapshot) values (%s,%s,'published','x',99,99,%s,now(),'[{}]')",
                (world.A["id"], world.A["video_draft"], world.ca),
            )


def test_role_escalation_blocked(world, as_, admin_conn):
    with as_(world.ca) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("update public.profiles set role='admin' where id=%s", (world.ca,))
    with as_(
        world.ca,
        extra_claims={"user_metadata": {"role": "admin"}, "app_metadata": {"role": "admin"}},
    ) as c:
        assert not c.execute("select public.is_admin()").fetchone()[0]
    uid = world.user("sneaky@x.test", meta={"role": "admin"})
    assert (
        admin_conn.execute("select role from public.profiles where id=%s", (uid,)).fetchone()[0]
        == "client"
    )


def test_user_can_update_only_own_name(world, as_):
    with as_(world.ca) as c:
        assert (
            c.execute("update public.profiles set full_name='B' where id=%s", (world.ca,)).rowcount
            == 1
        )
        assert (
            c.execute("update public.profiles set full_name='E' where id=%s", (world.cb,)).rowcount
            == 0
        )


# ---- integrity ----


def test_weights_must_total_100_at_commit(world, dsn):
    with psycopg.connect(dsn) as c:
        c.execute(
            "update public.work_packages set weight_percentage=50 where id=%s", (world.A["wp1"],)
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.commit()
    with psycopg.connect(dsn) as c:  # replacing the whole configuration in one tx is fine
        c.execute(
            "update public.work_packages set weight_percentage=50 where id=%s", (world.A["wp1"],)
        )
        c.execute(
            "update public.work_packages set weight_percentage=50 where id=%s", (world.A["wp2"],)
        )
        c.commit()


def test_published_report_is_immutable(world, admin_conn):
    for sql in (
        "update public.progress_reports set summary='changed' where id=%s",
        "delete from public.progress_reports where id=%s",
    ):
        with pytest.raises(psycopg.errors.Error, match="immutable"):
            admin_conn.execute(sql, (world.A["report_pub"],))


def test_cannot_cross_project_link(world, admin_conn):
    free = admin_conn.execute(
        "insert into public.drone_videos (project_id,storage_path,original_filename,"
        "capture_date) values (%s,'b/free.mp4','f.mp4','2026-02-01') returning id",
        (world.B["id"],),
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.ForeignKeyViolation):  # video of B inside a report of A
        admin_conn.execute(
            "insert into public.progress_reports (project_id,video_id) values (%s,%s)",
            (world.A["id"], free),
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):  # package of B on an observation of A
        admin_conn.execute(
            "update public.ai_observations set work_package_id=%s where id=%s",
            (world.B["wp1"], world.A["obs_pub"]),
        )


def test_observation_requires_evidence(world, admin_conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "insert into public.ai_observations (analysis_id,project_id,title,description,"
            "observation_type,confidence,evidence_frames,ai_original) values "
            "(%s,%s,'t','d','ongoing',0.5,'[]','{}')",
            (world.A["analysis_pub"], world.A["id"]),
        )


def test_publish_requires_package_progress(world, admin_conn):
    with pytest.raises(psycopg.errors.Error):
        admin_conn.execute(
            "update public.progress_reports set status='published', summary='s',"
            "overall_progress_percentage=1, assessment_coverage_percentage=1,"
            "package_progress_snapshot='[]', published_by=%s, published_at=now() where id=%s",
            (world.admin, world.A["report_draft"]),
        )


def test_one_active_job_per_video(world, admin_conn):
    with pytest.raises(psycopg.errors.UniqueViolation):
        admin_conn.execute(
            "insert into public.video_processing_jobs (video_id) values (%s)",
            (world.A["video_draft"],),
        )


def test_job_claiming(world, admin_conn):
    assert len(admin_conn.execute("select * from public.claim_next_job()").fetchall()) == 1
    assert len(admin_conn.execute("select * from public.claim_next_job()").fetchall()) == 1
    assert (
        admin_conn.execute("select count(*) from public.claim_next_job()").fetchone()[0] == 0
    )  # none left
    assert (
        admin_conn.execute(
            "select count(*) from public.video_processing_jobs where status='running'"
        ).fetchone()[0]
        == 2
    )
    # stale lock => re-claimed with attempts+1
    admin_conn.execute(
        "update public.video_processing_jobs set locked_at = now() - interval '1 hour'"
    )
    row = admin_conn.execute("select attempts from public.claim_next_job()").fetchone()
    assert row[0] == 2
    # exhausted attempts => failed, video failed
    admin_conn.execute(
        "update public.video_processing_jobs set locked_at = now() - interval '1 hour',"
        " attempts = max_attempts"
    )
    admin_conn.execute("select * from public.claim_next_job()")
    assert (
        admin_conn.execute(
            "select count(*) from public.video_processing_jobs where status='failed'"
        ).fetchone()[0]
        == 2
    )


def test_claim_not_callable_by_users(world, as_):
    with as_(world.admin) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("select * from public.claim_next_job()")


# ---- storage ----


def test_storage_client_reads_only_published_assets(world, as_):
    with as_(world.ca) as c:
        names = ids(c, "select name from storage.objects")
    assert world.A["path_pub"] in names and world.A["path_draft"] not in names
    assert world.A["fpath_pub"] in names and world.A["fpath_draft"] not in names
    assert not any(n.startswith(world.B["id"]) for n in names)


def test_storage_client_cannot_write(world, as_):
    with as_(world.ca) as c:
        with pytest.raises(psycopg.errors.Error):
            c.execute(
                "insert into storage.objects (bucket_id,name) values ('drone-videos','x/evil.mp4')"
            )
