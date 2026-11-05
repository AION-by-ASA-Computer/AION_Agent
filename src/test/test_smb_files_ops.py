"""Unit tests for smb_files ops/extract/client with a fake in-memory smbclient."""

import io
import stat as st
from types import SimpleNamespace

import pytest

from src.tools.smb_files import auth_guard, client, extract, ops
from src.tools.smb_files.settings_store import SmbConfig, SmbShare

CFG = SmbConfig(
    host="fs01",
    shares=(SmbShare("Documenti"), SmbShare("Archivio", read_only=True)),
    max_read_mb=1,
    max_write_mb=1,
)


class FakeSmb:
    """Minimal smbclient stand-in backed by a dict {unc: bytes|None(dir)}."""

    def __init__(self):
        self.fs = {"\\\\fs01\\Documenti": None, "\\\\fs01\\Archivio": None}
        self.registered = 0

    def register_session(self, *a, **k):
        self.registered += 1

    def _stat(self, unc):
        if unc not in self.fs:
            raise FileNotFoundError(unc)
        v = self.fs[unc]
        return SimpleNamespace(
            st_mode=st.S_IFDIR if v is None else st.S_IFREG,
            st_size=0 if v is None else len(v),
            st_mtime=1,
        )

    stat = _stat

    def scandir(self, unc):
        pre = unc + "\\"
        for k in list(self.fs):
            if k.startswith(pre) and "\\" not in k[len(pre) :]:
                yield SimpleNamespace(
                    name=k[len(pre) :], stat=lambda k=k: self._stat(k)
                )

    def open_file(self, unc, mode="rb"):
        if "r" in mode:
            return io.BytesIO(self.fs[unc])
        fake = self

        class W(io.BytesIO):
            def close(s):
                fake.fs[unc] = s.getvalue()
                super().close()

        return W()

    def makedirs(self, unc, exist_ok=False):
        self.fs[unc] = None

    def mkdir(self, unc):
        self.fs[unc] = None

    def rename(self, a, b):
        self.fs[b] = self.fs.pop(a)

    replace = rename


@pytest.fixture
def smb(monkeypatch, tmp_path):
    fake = FakeSmb()
    monkeypatch.setattr(ops, "_smb", lambda: fake)
    monkeypatch.setattr("smbclient.register_session", fake.register_session)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SMB_USERNAME", "ACME\\mario")
    monkeypatch.setenv("SMB_PASSWORD", "pw")
    return fake


class TestOps:
    """Scenario: read/write rules on allowed and read-only shares."""

    def test_write_then_read_roundtrip(self, smb):
        assert ops.write_text(CFG, "Documenti/a.txt", "ciao")["ok"]
        r = ops.read_file(CFG, "Documenti/a.txt")
        assert r["ok"] and r["text"] == "ciao" and not r["truncated"]

    def test_no_overwrite_by_default(self, smb):
        ops.write_text(CFG, "Documenti/a.txt", "1")
        r = ops.write_text(CFG, "Documenti/a.txt", "2")
        assert r["error"] == "already_exists"
        assert ops.write_text(CFG, "Documenti/a.txt", "2", overwrite=True)[
            "overwritten"
        ]

    def test_read_only_share_blocks_all_writes(self, smb):
        for r in (
            ops.write_text(CFG, "Archivio/a.txt", "x"),
            ops.mkdir(CFG, "Archivio/d"),
            ops.move(CFG, "Archivio/a", "Archivio/b"),
        ):
            assert r["error"] == "share_read_only"

    def test_size_limits(self, smb):
        big = "x" * (2 * 1024 * 1024)
        assert ops.write_text(CFG, "Documenti/b.txt", big)["error"] == "too_large"
        smb.fs["\\\\fs01\\Documenti\\big.bin"] = b"0" * (2 * 1024 * 1024)
        assert ops.read_file(CFG, "Documenti/big.bin")["error"] == "too_large"

    def test_cross_share_move_rejected(self, smb):
        ops.write_text(CFG, "Documenti/a.txt", "1")
        assert (
            ops.move(CFG, "Documenti/a.txt", "Archivio/a.txt")["error"]
            == "cross_share_move"
        )

    def test_move_and_missing_file(self, smb):
        ops.write_text(CFG, "Documenti/a.txt", "1")
        assert ops.move(CFG, "Documenti/a.txt", "Documenti/b.txt")["ok"]
        assert ops.stat(CFG, "Documenti/a.txt")["error"] == "not_found"

    def test_list_and_search(self, smb):
        ops.mkdir(CFG, "Documenti/sub")
        ops.write_text(CFG, "Documenti/sub/report.txt", "r")
        names = [e["name"] for e in ops.list_dir(CFG, "Documenti")["entries"]]
        assert names == ["sub"]
        res = ops.search(CFG, "Documenti", "report")["results"]
        assert res[0]["path"] == "Documenti/sub/report.txt"

    def test_no_config_and_bad_path(self, smb):
        assert ops.list_dir(None, "Documenti")["error"] == "not_configured"
        assert ops.list_dir(CFG, "C$/x")["error"] == "share_not_allowed"

    def test_session_copy_and_upload(self, smb, monkeypatch, tmp_path):
        monkeypatch.setenv("AION_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("AION_CHAT_SESSION_ID", "sess-1234")
        ops.write_text(CFG, "Documenti/a.txt", "dati")
        c = ops.copy_to_session(CFG, "Documenti/a.txt")
        assert c["ok"] and c["session_path"] == "workspace/smb/a.txt"
        u = ops.upload_from_session(CFG, "Documenti/copy.txt", c["session_path"])
        assert u["ok"] and smb.fs["\\\\fs01\\Documenti\\copy.txt"] == b"dati"


class TestCredentialsAndGuard:
    """Scenario: no network without real credentials; one logon failure only."""

    def test_missing_credentials_no_network(self, smb, monkeypatch):
        monkeypatch.setenv("SMB_PASSWORD", "probe_secret_key")
        assert ops.list_dir(CFG, "Documenti")["error"] == "credentials_missing"
        assert smb.registered == 0

    def test_single_attempt_then_local_block(self, smb, monkeypatch):
        from smbprotocol.exceptions import LogonFailure

        calls = []

        def boom(*a, **k):
            calls.append(1)
            raise LogonFailure()

        monkeypatch.setattr("smbclient.register_session", boom)
        assert ops.list_dir(CFG, "Documenti")["error"] == "auth_failed"
        assert ops.list_dir(CFG, "Documenti")["error"] == "auth_failed"
        assert len(calls) == 1  # second call blocked locally
        monkeypatch.setenv("SMB_PASSWORD", "new-pw")
        ops.list_dir(CFG, "Documenti")
        assert len(calls) == 2  # new credentials -> retried

    def test_exception_mapping(self):
        assert client.map_exception(PermissionError())[0] == "access_denied"
        assert client.map_exception(TimeoutError())[0] == "timeout"
        assert client.map_exception(ConnectionRefusedError())[0] == "unreachable"
        assert "auth_failed" in auth_guard.LOGON_CODES


class TestExtract:
    """Scenario: text extraction for DOCX/XLSX/text, pagination, binary hint."""

    def test_docx_and_xlsx(self):
        from docx import Document
        from openpyxl import Workbook

        d = Document()
        d.add_paragraph("Hello docx")
        buf = io.BytesIO()
        d.save(buf)
        assert "Hello docx" in extract.extract_text(buf.getvalue(), "a.docx")["text"]

        wb = Workbook()
        wb.active["A1"], wb.active["B1"] = "x", 5
        buf = io.BytesIO()
        wb.save(buf)
        assert "x\t5" in extract.extract_text(buf.getvalue(), "a.xlsx")["text"]

    def test_pagination(self):
        r = extract.extract_text(b"abcdefghij", "a.txt", max_chars=4)
        assert (r["text"], r["truncated"], r["next_offset"]) == ("abcd", True, 4)
        r = extract.extract_text(b"abcdefghij", "a.txt", max_chars=10, offset_chars=4)
        assert r["text"] == "efghij" and not r["truncated"]

    def test_unsupported_gives_ocr_hint(self):
        assert "smb_copy_to_session" in extract.extract_text(b"\x00", "a.png")["hint"]
