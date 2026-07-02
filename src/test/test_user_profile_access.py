import pytest
from sqlalchemy import select, delete
from src.data.engine import get_async_session_maker
from src.data.models import User, UserProfileAccess
from src.api.main import get_allowed_profiles_for_user
from src.main import get_agent
from src.agent_profile import profile_manager, ProfileNotFoundError


@pytest.mark.anyio
async def test_user_profile_access_mapping(monkeypatch):
    # Mock resolve_profile to avoid starting MCP servers during test
    original_resolve = profile_manager.resolve_profile

    def mock_resolve(name):
        p = original_resolve(name)
        import copy

        p_copy = copy.copy(p)
        p_copy.mcp_servers = []
        return p_copy

    monkeypatch.setattr(profile_manager, "resolve_profile", mock_resolve)

    # 1. Create a dummy user and add access rules
    async with get_async_session_maker()() as session:
        # Check if dummy user exists or create
        u = await session.get(User, "test_access_user")
        if not u:
            u = User(
                id="test_access_user",
                tenant_id="default",
                identifier="test_access_user",
                display_name="Test Access User",
                roles_json="[]",
            )
            session.add(u)
        else:
            # Clear existing access
            await session.execute(
                delete(UserProfileAccess).where(
                    UserProfileAccess.user_id == "test_access_user"
                )
            )

        # Add profile access to a specific fake profile slug
        access = UserProfileAccess(
            user_id="test_access_user",
            tenant_id="default",
            profile_slug="coding_workspace",
        )
        session.add(access)
        await session.commit()

    # 2. Test get_allowed_profiles_for_user filters
    allowed = await get_allowed_profiles_for_user("test_access_user")
    slugs = [p["slug"] for p in allowed]
    assert "coding_workspace" in slugs
    assert "aion_std" not in slugs

    # 3. Test get_agent fallback logic
    # "aion_std" should fallback to "coding_workspace" (since aion_std is not allowed, it falls back to first allowed)
    agent, profile_name = await get_agent(
        profile_name="aion_std",
        session_id="test_sess_access",
        user_id="test_access_user",
    )
    assert profile_name == "coding_workspace"

    # 4. Test get_agent raises ProfileNotFoundError for unallowed profiles other than aion_std
    with pytest.raises(ProfileNotFoundError):
        await get_agent(
            profile_name="infra_sre",  # infra_sre is a real profile but not allowed for this user
            session_id="test_sess_access",
            user_id="test_access_user",
        )

    # Clean up
    async with get_async_session_maker()() as session:
        await session.execute(
            delete(UserProfileAccess).where(
                UserProfileAccess.user_id == "test_access_user"
            )
        )
        u = await session.get(User, "test_access_user")
        if u:
            await session.delete(u)
        await session.commit()
