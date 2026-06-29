import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.data.bootstrap import ensure_bootstrap_schema
from src.data.user_password import UserAlreadyExistsError, create_password_user


@pytest.fixture()
def tmp_sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'pw.db'}"


def test_create_password_user_duplicate_per_tenant(tmp_sqlite_url: str) -> None:
    async def run() -> None:
        eng = create_async_engine(tmp_sqlite_url)
        await ensure_bootstrap_schema(eng)
        sm = async_sessionmaker(eng, expire_on_commit=False)

        uid = await create_password_user(
            tenant_id="default",
            identifier="alice",
            password="secret-one",
            session_maker=sm,
        )
        assert uid

        with pytest.raises(UserAlreadyExistsError):
            await create_password_user(
                tenant_id="default",
                identifier="alice",
                password="other",
                session_maker=sm,
            )

        uid2 = await create_password_user(
            tenant_id="other",
            identifier="alice",
            password="secret-two",
            session_maker=sm,
        )
        assert uid2 != uid

        await eng.dispose()

    asyncio.run(run())
