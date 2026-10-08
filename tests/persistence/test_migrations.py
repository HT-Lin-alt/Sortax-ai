from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

PROJECT_ROOT = Path(__file__).parents[2]


def test_initial_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.sqlite3"
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) >= {
            "alembic_version",
            "conversations",
            "generation_runs",
            "message_citations",
            "messages",
            "retrieval_runs",
        }
        assert "completion_kind" in {column["name"] for column in inspector.get_columns("messages")}
    finally:
        engine.dispose()

    command.downgrade(config, "base")

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()
