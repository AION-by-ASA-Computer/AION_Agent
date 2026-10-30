"""Codici ``COLLEGA``: scadenza, riuso, tentativi, ricollegamento, cambio numero."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from src.test.whatsapp_test_helpers import DISPLAY_PHONE, TENANT

BSUID = "IT.1111111111111111"


def test_parse_link_command():
    from src.channels.whatsapp.linking import parse_link_command

    assert parse_link_command("COLLEGA 7KQ4M2XP") == "7KQ4M2XP"
    assert parse_link_command("  collega 7kq4-m2xp ") == "7KQ4M2XP"
    assert parse_link_command("collega 7kq4 m2xp") == "7KQ4M2XP"
    assert parse_link_command("ciao") is None
    assert parse_link_command("COLLEGA") is None
    assert parse_link_command(None) is None


def test_wa_link_and_phone_hint():
    from src.channels.whatsapp.linking import phone_hint, wa_link

    assert wa_link(DISPLAY_PHONE, "ABCD2345") == (
        "https://wa.me/390212345678?text=COLLEGA%20ABCD2345"
    )
    assert wa_link(None, "ABCD2345") is None
    assert phone_hint("+39 333 111 2233") == "••• 233"
    assert phone_hint(None) is None


async def _consume(code, bsuid=BSUID, phone="393331112233"):
    from src.channels.whatsapp import linking

    return await linking.consume_code(
        TENANT, code=code, bsuid=bsuid, phone=phone, profile_name="Mario"
    )


@pytest.mark.anyio
async def test_create_and_consume(wa_db, monkeypatch, tmp_path):
    from src.channels.whatsapp import linking

    link = await linking.create_link_code(TENANT, "u1", DISPLAY_PHONE)
    assert len(link.code) == 8
    assert set(link.code) <= set(linking.CODE_ALPHABET)
    assert link.wa_link and link.code in link.wa_link
    assert link.qr_svg and link.qr_svg.startswith("data:image/svg+xml")

    res = await _consume(link.code.lower())
    assert res.ok and res.reason == "linked" and res.user.id == "u1"

    ident = await linking.get_identity(TENANT, BSUID)
    assert ident.user_id == "u1"
    assert ident.phone_e164 == "393331112233"
    assert ident.wa_profile_name == "Mario"
    assert (await linking.get_identity_for_user(TENANT, "u1")).id == ident.id

    # Monouso.
    again = await _consume(link.code)
    assert not again.ok and again.reason == "invalid"


@pytest.mark.anyio
async def test_new_code_invalidates_previous(wa_db, monkeypatch, tmp_path):
    from src.channels.whatsapp import linking

    first = await linking.create_link_code(TENANT, "u1", DISPLAY_PHONE)
    second = await linking.create_link_code(TENANT, "u1", DISPLAY_PHONE)
    assert (await _consume(first.code)).reason == "invalid"
    assert (await _consume(second.code)).ok


@pytest.mark.anyio
async def test_expired_code(wa_db, monkeypatch, tmp_path):
    from src.channels.whatsapp import linking
    from src.data.engine import get_async_session_maker
    from src.data.models import WhatsAppLinkCode

    link = await linking.create_link_code(TENANT, "u1", DISPLAY_PHONE)
    async with get_async_session_maker()() as session:
        await session.execute(
            update(WhatsAppLinkCode).values(
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        )
        await session.commit()
    res = await _consume(link.code)
    assert not res.ok and res.reason == "expired"


@pytest.mark.anyio
async def test_rate_limit_after_five_failures(wa_db, monkeypatch, tmp_path):
    from src.channels.whatsapp import linking

    link = await linking.create_link_code(TENANT, "u1", DISPLAY_PHONE)
    for _ in range(linking.MAX_FAILED_ATTEMPTS):
        assert (await _consume("ZZZZZZZZ")).reason == "invalid"
    # Anche il codice giusto viene rifiutato finché la finestra non scade.
    assert (await _consume(link.code)).reason == "rate_limited"
    # Un altro mittente non è bloccato.
    assert (await _consume(link.code, bsuid="IT.other")).ok


@pytest.mark.anyio
async def test_relink_replaces_both_sides(wa_db, monkeypatch, tmp_path):
    from src.channels.whatsapp import linking

    # u1 collega il telefono A, poi lo stesso telefono A viene collegato a u2.
    assert (
        await _consume((await linking.create_link_code(TENANT, "u1", None)).code)
    ).ok
    assert (
        await _consume((await linking.create_link_code(TENANT, "u2", None)).code)
    ).ok
    assert (await linking.get_identity(TENANT, BSUID)).user_id == "u2"
    assert await linking.get_identity_for_user(TENANT, "u1") is None

    # u2 collega un secondo telefono B: A non è più collegato.
    code = (await linking.create_link_code(TENANT, "u2", None)).code
    assert (await _consume(code, bsuid="IT.B", phone=None)).ok
    assert await linking.get_identity(TENANT, BSUID) is None
    assert (await linking.get_identity_for_user(TENANT, "u2")).bsuid == "IT.B"
    assert len(await linking.list_identities(TENANT)) == 1


@pytest.mark.anyio
async def test_phone_fallback_backfills_bsuid(wa_db, monkeypatch, tmp_path):
    from src.channels.whatsapp import linking

    code = (await linking.create_link_code(TENANT, "u1", None)).code
    # Payload senza BSUID: la chiave è il numero.
    assert (await _consume(code, bsuid="393331112233", phone="393331112233")).ok
    ident = await linking.get_identity(TENANT, BSUID, "393331112233")
    assert ident is not None and ident.bsuid == BSUID
    assert (await linking.get_identity(TENANT, BSUID)).user_id == "u1"


@pytest.mark.anyio
async def test_number_change_and_unlink(wa_db, monkeypatch, tmp_path):
    from src.channels.whatsapp import linking

    assert (
        await _consume((await linking.create_link_code(TENANT, "u1", None)).code)
    ).ok
    assert await linking.apply_number_change(
        TENANT, previous_bsuid=BSUID, new_bsuid=None, new_phone="393339998877"
    )
    assert (await linking.get_identity(TENANT, BSUID)).phone_e164 == "393339998877"

    assert await linking.apply_number_change(
        TENANT, previous_bsuid=BSUID, new_bsuid="IT.NEW", new_phone=None
    )
    assert await linking.get_identity(TENANT, BSUID) is None
    ident = await linking.get_identity(TENANT, "IT.NEW")
    assert ident.user_id == "u1"

    assert not await linking.apply_number_change(
        TENANT, previous_bsuid="IT.unknown", new_bsuid=None, new_phone="1"
    )

    (item,) = await linking.list_identities(TENANT)
    assert item["user_identifier"] == "mario"
    assert item["phone_hint"] == "••• 877"

    assert await linking.unlink(TENANT, identity_id=ident.id)
    assert not await linking.unlink(TENANT, identity_id=ident.id)
    assert not await linking.unlink(TENANT)
