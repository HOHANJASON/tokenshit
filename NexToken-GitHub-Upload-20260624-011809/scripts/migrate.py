from pathlib import Path
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import engine  # noqa: E402


def main() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    tables = set(inspect(engine).get_table_names())
    if tables and "alembic_version" not in tables:
        expected = {"customers", "providers", "model_configs", "api_keys", "ledger", "usage_logs"}
        if not expected.issubset(tables):
            raise RuntimeError("Database contains an unknown partial schema; migration was stopped.")
        command.stamp(config, "head")
        print("Existing NexToken schema registered at the current migration revision.")
    else:
        command.upgrade(config, "head")
        print("Database migrations are current.")


if __name__ == "__main__":
    main()
