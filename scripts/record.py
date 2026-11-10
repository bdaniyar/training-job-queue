"""Run a command once and retain unedited stdout/stderr, even when it fails."""

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tarfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def main() -> int:
    command = sys.argv[1:]
    if not command:
        raise SystemExit("usage: python scripts/record.py COMMAND [ARG ...]")
    started = datetime.now(UTC)
    run = Path("artifacts/runs") / (
        started.strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    )
    run.mkdir(parents=True)
    paths = git("ls-files", "--cached", "--others", "--exclude-standard").splitlines()
    sources = {
        name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
        for name in paths
        if Path(name).is_file() and not name.startswith("artifacts/")
    }
    db = urlsplit(os.environ.get("TEST_DATABASE_URL", os.environ.get("QUEUE_DATABASE_URL", "")))
    metadata = {
        "command": command,
        "started_at": started.isoformat(),
        "commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "status": git("status", "--short"),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "dependencies": {
            item.metadata["Name"]: item.version
            for item in importlib.metadata.distributions()
            if item.metadata["Name"].lower()
            in {
                "fastapi",
                "sqlalchemy",
                "asyncpg",
                "httpx",
                "pydantic",
                "alembic",
                "pytest",
                "ruff",
            }
        },
        "configuration": {
            key: os.environ[key]
            for key in (
                "QUEUE_API_PORT",
                "QUEUE_DB_PORT",
                "QUEUE_LEASE_SECONDS",
                "QUEUE_HEARTBEAT_SECONDS",
                "QUEUE_ATTEMPT_SECONDS",
            )
            if key in os.environ
        },
        "database": {"host": db.hostname, "port": db.port, "database": db.path},
        "source_sha256": sources,
    }
    (run / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (run / "dirty.patch").write_text(git("diff", "HEAD") + "\n")
    with tarfile.open(run / "source.tar.gz", "w:gz") as snapshot:
        for name in sources:
            snapshot.add(name, arcname=name, recursive=False)
    print(f"Evidence: {run}", flush=True)

    def copy(stream, filename, target):
        with (run / filename).open("wb") as output:
            while chunk := stream.read(4096):
                output.write(chunk)
                output.flush()
                target.buffer.write(chunk)
                target.flush()

    try:
        environment = os.environ | {"QUEUE_RUN_DIR": str(run.resolve())}
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment
        )
    except OSError as exc:
        (run / "stderr.txt").write_text(str(exc) + "\n")
        (run / "stdout.txt").touch()
        code = 127
    else:
        threads = [
            threading.Thread(target=copy, args=(process.stdout, "stdout.txt", sys.stdout)),
            threading.Thread(target=copy, args=(process.stderr, "stderr.txt", sys.stderr)),
        ]
        for thread in threads:
            thread.start()
        try:
            code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            code = process.wait()
        for thread in threads:
            thread.join()
    (run / "result.json").write_text(
        json.dumps({"exit_code": code, "ended_at": datetime.now(UTC).isoformat()}) + "\n"
    )
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    raise SystemExit(main())
