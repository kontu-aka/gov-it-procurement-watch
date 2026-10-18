"""Explicit public-sample entrypoint; never select local production data."""

from pathlib import Path

app_path = Path(__file__).resolve().with_name("app.py")
# Each rerun gets its own namespace; no process-wide environment or argv changes.
exec(
    compile(app_path.read_bytes(), str(app_path), "exec"),
    {"__name__": "__main__", "__file__": str(app_path), "PUBLIC_SAMPLE_ONLY": True},
)
