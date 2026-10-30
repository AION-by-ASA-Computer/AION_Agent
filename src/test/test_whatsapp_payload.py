"""Parsing dei webhook Cloud API (fixture in ``fixtures/whatsapp``)."""

from src.channels.whatsapp.payload import InboundMessage, parse_webhook
from src.test.whatsapp_test_helpers import PNID, load_fixture


def test_text_with_phone():
    parsed = parse_webhook(load_fixture("text_with_phone"))
    assert parsed.phone_number_ids == [PNID]
    assert parsed.statuses == []
    (msg,) = parsed.messages
    assert msg.wamid == "wamid.TEXT1"
    assert msg.bsuid == "IT.1111111111111111"
    assert msg.phone == "393331112233"
    assert msg.profile_name == "Mario Rossi"
    assert msg.type == "text"
    assert msg.text == "Quanti ordini ieri?"
    assert msg.timestamp == 1761650000
    assert msg.sender_key == "IT.1111111111111111"


def test_text_bsuid_only():
    (msg,) = parse_webhook(load_fixture("text_bsuid_only")).messages
    assert msg.bsuid == "IT.2222222222222222"
    assert msg.phone is None
    assert msg.profile_name == "Giulia"
    assert msg.text == "ciao"
    assert msg.sender_key == "IT.2222222222222222"


def test_phone_only_sender_key_falls_back_to_phone():
    body = load_fixture("text_with_phone")
    value = body["entry"][0]["changes"][0]["value"]
    del value["messages"][0]["from_user_id"]
    del value["contacts"][0]["user_id"]
    (msg,) = parse_webhook(body).messages
    assert msg.bsuid is None
    assert msg.sender_key == "393331112233"
    assert msg.profile_name == "Mario Rossi"


def test_statuses():
    parsed = parse_webhook(load_fixture("status"))
    assert parsed.messages == []
    delivered, failed = parsed.statuses
    assert (delivered.wamid, delivered.status) == ("wamid.OUT1", "delivered")
    assert delivered.bsuid == "IT.1111111111111111"
    assert delivered.phone == "393331112233"
    assert (failed.status, failed.error_code) == ("failed", "131047")
    assert failed.error_title == "Re-engagement message"


def test_number_change():
    (msg,) = parse_webhook(load_fixture("number_change")).messages
    assert msg.type == "system"
    assert msg.system is not None
    assert msg.system.kind == "user_changed_number"
    assert msg.system.previous_bsuid == "IT.1111111111111111"
    assert msg.system.previous_phone == "393331112233"
    assert msg.system.new_phone == "393339998877"


def test_image_caption_becomes_text():
    """The image object is kept as ``media`` and its caption is the turn text."""
    (msg,) = parse_webhook(load_fixture("image")).messages
    assert msg.type == "image"
    assert msg.text == "scontrino"
    assert msg.media is not None
    assert (msg.media.id, msg.media.mime_type) == ("MEDIA1", "image/jpeg")
    assert msg.media.sha256 == "abc"


def test_image_without_caption():
    """No caption -> no text; the webhook ``url`` (Oct 2025 rollout) is kept."""
    (msg,) = parse_webhook(load_fixture("image_no_caption")).messages
    assert msg.text is None
    assert msg.media.url.startswith("https://lookaside.fbsbx.com/")


def test_document_keeps_filename_and_caption():
    (msg,) = parse_webhook(load_fixture("document_pdf")).messages
    assert msg.type == "document"
    assert msg.text == "riassumi questa fattura"
    assert msg.media.filename == "Fattura marzo.pdf"
    assert msg.media.mime_type == "application/pdf"


def test_voice_note_has_media_but_no_text():
    """Audio has no caption: parsed as media so the dispatcher can decline it."""
    (msg,) = parse_webhook(load_fixture("audio_voice")).messages
    assert msg.type == "audio"
    assert msg.text is None
    assert msg.media.voice is True


def test_roundtrip_dict():
    """``to_dict``/``from_dict`` (queued payload) preserve system and media data."""
    for name in ("text_with_phone", "number_change", "image", "document_pdf"):
        (msg,) = parse_webhook(load_fixture(name)).messages
        assert InboundMessage.from_dict(msg.to_dict()) == msg


def test_tolerates_garbage():
    for body in (None, [], "x", {}, {"entry": "x"}, {"entry": [{"changes": [1]}]}):
        parsed = parse_webhook(body)
        assert parsed.messages == [] and parsed.statuses == []


def test_ignores_other_fields_and_messages_without_id():
    body = load_fixture("text_with_phone")
    change = body["entry"][0]["changes"][0]
    body["entry"][0]["changes"].append({**change, "field": "account_update"})
    change["value"]["messages"].append({"type": "text", "text": {"body": "x"}})
    assert len(parse_webhook(body).messages) == 1
