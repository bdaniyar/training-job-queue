"""Regenerate only the derived index; preserve every raw run, including failures."""

import json
from pathlib import Path


def main():
    rows = [
        "# Raw verification runs",
        "",
        "Generated index only; raw files are unedited. Times in IDs are UTC.",
        "",
        "| Run | Exit | Command (full command in metadata) |",
        "| --- | --- | --- |",
    ]
    for run in sorted(Path("artifacts/runs").iterdir()):
        meta = json.loads((run / "metadata.json").read_text())
        result_path = run / "result.json"
        code = (
            json.loads(result_path.read_text())["exit_code"] if result_path.exists() else "RUNNING"
        )
        command = " ".join(meta["command"]).replace("|", r"\|").replace("`", "'")
        if len(command) > 130:
            command = command[:127] + "..."
        rows.append(f"| [{run.name}](runs/{run.name}/metadata.json) | {code} | `{command}` |")
    Path("artifacts/INDEX.md").write_text("\n".join(rows) + "\n")
    print(f"Indexed {len(rows) - 6} raw runs, including in-progress recorder invocations.")


if __name__ == "__main__":
    main()
