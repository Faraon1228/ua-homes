"""Child process used by test_real_deletion_recovery (never run by hand).

Phases (argv[1]): lock | fail | crash | recover. Configuration comes from the
environment: UA_HOMES_DB_PATH (isolated SQLite), CLOUDINARY_URL (the confirmed TEST
cloud), RECOVERY_OWNER_ID (random high-entropy id that defines the only prefix used).
"""

import datetime
import importlib
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)
os.environ.pop("DATABASE_URL", None)
os.environ.setdefault("UA_HOMES_SECRET", "real-recovery-test-secret-at-least-32-bytes")

app_module = importlib.import_module("app")
jobs = importlib.import_module("account_deletion_jobs")
import bcrypt  # noqa: E402
import cloudinary  # noqa: E402
import cloudinary.api  # noqa: E402
import cloudinary.uploader  # noqa: E402

OWNER = int(os.environ["RECOVERY_OWNER_ID"])
PIXEL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
BASE = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def at(seconds):
    return BASE + datetime.timedelta(seconds=seconds)


def run(seconds):
    with app_module.app.app_context():
        return jobs.run_due_jobs(app_module.get_db(), app_module, now=at(seconds))


def lock():
    app_module.init_db()
    hashed = bcrypt.hashpw(b"correct-password", bcrypt.gensalt(rounds=4)).decode()
    with app_module.app.app_context():
        db = app_module.get_db()
        db.execute(
            "INSERT INTO users (id, name, email, password, password_hash, role, account_type, email_verified)"
            " VALUES (?, 'Recovery', 'recovery@example.test', ?, ?, 'user', 'owner', 1)",
            (OWNER, hashed, hashed),
        )
        db.commit()
    cloudinary.config(secure=True)
    for name in ("a/photo", "b/photo"):
        cloudinary.uploader.upload(PIXEL, public_id=f"listings/{OWNER}/{name}", overwrite=True, resource_type="image")
    token = app_module.make_token(OWNER, "recovery@example.test")
    client = app_module.app.test_client()
    response = client.post(
        "/api/auth/delete-account",
        json={"password": "correct-password", "confirm": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    print("delete-status", response.status_code)


def with_provider_fault(mode):
    real = cloudinary.api.delete_resources_by_prefix

    def faulty(*args, **kwargs):
        if mode == "fail":
            raise ConnectionError("injected network failure")
        result = real(*args, **kwargs)  # the real provider delete happens ...
        os._exit(137)  # ... then the process dies before the job records progress
        return result

    cloudinary.api.delete_resources_by_prefix = faulty


if __name__ == "__main__":
    phase = sys.argv[1]
    if phase == "lock":
        lock()
    elif phase in ("fail", "crash"):
        with_provider_fault(phase)
        print("outcome", run(5 if phase == "fail" else 400)["outcomes"])
    elif phase == "recover":
        for seconds in (2400, 2500, 12000):
            print("outcome", seconds, run(seconds)["outcomes"])
