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
            "tax_intake_sessions",
            "message_checklist_items",
        }
        message_columns = {column["name"] for column in inspector.get_columns("messages")}
        assert {"completion_kind", "content_type", "structured_content"} <= message_columns
        intake_columns = {column["name"] for column in inspector.get_columns("tax_intake_sessions")}
        assert {"version", "answer_updated_at"} <= intake_columns
        citation_columns = {column["name"] for column in inspector.get_columns("message_citations")}
        assert "claim_type" in citation_columns
    finally:
        engine.dispose()

    command.downgrade(config, "base")

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()
