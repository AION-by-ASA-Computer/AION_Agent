"""Markdown → WhatsApp e split dei messaggi lunghi."""

from src.channels.whatsapp.formatting import (
    markdown_to_whatsapp,
    prepare_reply,
    split_message,
)


def test_inline_styles():
    assert markdown_to_whatsapp("**grassetto**") == "*grassetto*"
    assert markdown_to_whatsapp("__grassetto__") == "*grassetto*"
    assert markdown_to_whatsapp("un *corsivo* qui") == "un _corsivo_ qui"
    assert markdown_to_whatsapp("~~via~~") == "~via~"


def test_headings_links_bullets():
    md = "## Riepilogo\n- uno\n* due\n[Docs](https://x.io) e [https://y.io](https://y.io)"
    assert markdown_to_whatsapp(md) == (
        "*Riepilogo*\n• uno\n• due\nDocs (https://x.io) e https://y.io"
    )


def test_horizontal_rule_removed():
    assert markdown_to_whatsapp("a\n\n---\n\nb") == "a\n\nb"


def test_table():
    md = "| Nome | Ordini |\n|---|---:|\n| Rossi | 3 |\n| Bianchi | 5 |"
    assert markdown_to_whatsapp(md) == "*Nome — Ordini*\n• Rossi — 3\n• Bianchi — 5"


def test_code_is_preserved():
    md = "usa `**non toccare**` e\n```python\nx = **2\n```"
    assert markdown_to_whatsapp(md) == "usa `**non toccare**` e\n```\nx = **2\n```"


def test_split_short_and_empty():
    assert split_message("ciao") == ["ciao"]
    assert split_message("   ") == []


def test_split_on_paragraphs_within_limit():
    text = "\n\n".join(["a" * 40] * 5)
    chunks = split_message(text, limit=100)
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks).replace("\n", "") == "a" * 200


def test_split_hard_cut_without_separators():
    chunks = split_message("x" * 250, limit=100)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_prepare_reply_truncates_with_link():
    text = "\n\n".join(f"paragrafo {i} " + "parola " * 10 for i in range(20))
    chunks = prepare_reply(
        text, continue_url="https://aion/c/1", max_chunks=2, limit=120
    )
    assert len(chunks) == 2
    assert all(len(c) <= 120 for c in chunks)
    assert chunks[-1].endswith("… Continua su AION: https://aion/c/1")


def test_prepare_reply_short_untouched():
    assert prepare_reply("**ok**", continue_url="u") == ["*ok*"]
