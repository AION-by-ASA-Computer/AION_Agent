import asyncio
from pathlib import Path
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.data.bootstrap import ensure_bootstrap_schema
from src.data.models import User
from src.api.auth_login import update_me, UpdateUserMetadata, issue_chat_token
from fastapi import HTTPException


@pytest.fixture()
def tmp_sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'pw.db'}"


def test_update_me_endpoint(tmp_sqlite_url: str, monkeypatch) -> None:
    async def run() -> None:
        # Arrange: Setup DB engine and session
        eng = create_async_engine(tmp_sqlite_url)
        await ensure_bootstrap_schema(eng)
        sm = async_sessionmaker(eng, expire_on_commit=False)

        # Monkeypatch the session maker so update_me uses our tmp DB
        import src.data.engine as engine

        monkeypatch.setattr(engine, "get_async_session_maker", lambda: sm)

        # Insert test users
        from src.data.user_password import create_password_user

        uid1 = await create_password_user(
            tenant_id="default",
            identifier="alice",
            password="secret-one",
            session_maker=sm,
        )
        assert uid1

        uid2 = await create_password_user(
            tenant_id="default",
            identifier="bob",
            password="secret-two",
            session_maker=sm,
        )
        assert uid2

        # Create auth token for alice
        token = issue_chat_token(user_row_id=uid1, user_identifier="alice")
        auth_header = f"Bearer {token}"

        # 1. Test update display_name and email
        body1 = UpdateUserMetadata(
            display_name="Alice in Wonderland", email="alice@wonderland.com"
        )
        res1 = await update_me(body=body1, authorization=auth_header)
        assert res1["display_name"] == "Alice in Wonderland"
        assert res1["email"] == "alice@wonderland.com"
        assert res1["identifier"] == "alice"

        # 2. Test update identifier (username)
        body2 = UpdateUserMetadata(identifier="alice_new")
        res2 = await update_me(body=body2, authorization=auth_header)
        assert res2["identifier"] == "alice_new"
        assert res2["display_name"] == "Alice in Wonderland"

        # 3. Test empty identifier raises 400
        with pytest.raises(HTTPException) as exc_info:
            await update_me(
                body=UpdateUserMetadata(identifier="   "), authorization=auth_header
            )
        assert exc_info.value.status_code == 400
        assert "cannot be empty" in exc_info.value.detail

        # 4. Test duplicate identifier raises 400
        # Bob already exists in "default" tenant. Alice trying to rename to "bob" should fail.
        with pytest.raises(HTTPException) as exc_info:
            await update_me(
                body=UpdateUserMetadata(identifier="bob"), authorization=auth_header
            )
        assert exc_info.value.status_code == 400
        assert "already taken" in exc_info.value.detail

        await eng.dispose()

    asyncio.run(run())
