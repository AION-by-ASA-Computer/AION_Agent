"""Unit tests for smb_files ops/extract/client with a fake in-memory smbclient.

Two servers are configured (``fs01`` with the DEFAULT credential set,
``fs02`` with the ``ESTERO`` set) to cover server routing, per-set
credentials and the per-set auth guard.
"""

import io
import json
import stat as st
from types import SimpleNamespace

import pytest

from src.tools.smb_files import auth_guard, client, extract, ops
from src.tools.smb_files.credentials import EXTRA_ENV
from src.tools.smb_files.settings_store import SmbConfig, SmbServer, SmbShare

CFG = SmbConfig(
    servers=(
        SmbServer(
            alias="fs01",
            host="fs01",
            label="Sede",
            shares=(SmbShare("Documenti"), SmbShare("Archivio", read_only=True)),
        ),
        SmbServer(
            alias="fs02",
            host="fs02.estero.local",
            credential_set="ESTERO",
            shares=(SmbShare("Documenti"),),
        ),
    ),
    max_read_mb=1,
    max_write_mb=1,
)


class FakeSmb:
    """Minimal smbclient stand-in backed by a dict {unc: bytes|None(dir)}."""

    def __init__(self):
        self.fs = {
            "\\\\fs01\\Documenti": None,
            "\\\\fs01\\Archivio": None,
            "\\\\fs02.estero.local\\Documenti": None,
        }
        self.registered = 0
        self.sessions = []  # (host, username) of every register_session call

    def register_session(self, host, username=None, **k):
        self.registered += 1
        self.sessions.append((host, username))

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
    monkeypatch.setenv(
        EXTRA_ENV,
        json.dumps({"SMB_USERNAME__ESTERO": "ESTERO\\m.rossi", "SMB_PASSWORD__ESTERO": "pw2"}),
    )
    return fake


class TestOps:
    """Scenario: read/write rules on allowed and read-only shares."""

    def test_write_then_read_roundtrip(self, smb):
        assert ops.write_text(CFG, "fs01/Documenti/a.txt", "ciao")["ok"]
        r = ops.read_file(CFG, "fs01/Documenti/a.txt")
        assert r["ok"] and r["text"] == "ciao" and not r["truncated"]

    def test_no_overwrite_by_default(self, smb):
        ops.write_text(CFG, "fs01/Documenti/a.txt", "1")
        r = ops.write_text(CFG, "fs01/Documenti/a.txt", "2")
        assert r["error"] == "already_exists"
        assert ops.write_text(CFG, "fs01/Documenti/a.txt", "2", overwrite=True)[
            "overwritten"
        ]

    def test_read_only_share_blocks_all_writes(self, smb):
        for r in (
            ops.write_text(CFG, "fs01/Archivio/a.txt", "x"),
            ops.mkdir(CFG, "fs01/Archivio/d"),
            ops.move(CFG, "fs01/Archivio/a", "fs01/Archivio/b"),
        ):
            assert r["error"] == "share_read_only"

    def test_size_limits(self, smb):
        big = "x" * (2 * 1024 * 1024)
        assert ops.write_text(CFG, "fs01/Documenti/b.txt", big)["error"] == "too_large"
        smb.fs["\\\\fs01\\Documenti\\big.bin"] = b"0" * (2 * 1024 * 1024)
        assert ops.read_file(CFG, "fs01/Documenti/big.bin")["error"] == "too_large"

    def test_cross_share_move_rejected(self, smb):
        ops.write_text(CFG, "fs01/Documenti/a.txt", "1")
        assert (
            ops.move(CFG, "fs01/Documenti/a.txt", "fs01/Archivio/a.txt")["error"]
            == "cross_share_move"
        )

    def test_cross_server_move_rejected(self, smb):
        """Same share name on two servers is still a cross-server move."""
        ops.write_text(CFG, "fs01/Documenti/a.txt", "1")
        assert (
            ops.move(CFG, "fs01/Documenti/a.txt", "fs02/Documenti/a.txt")["error"]
            == "cross_share_move"
        )

    def test_each_server_uses_its_host_and_credential_set(self, smb):
        assert ops.write_text(CFG, "fs02/Documenti/b.txt", "x")["ok"]
        assert smb.fs["\\\\fs02.estero.local\\Documenti\\b.txt"] == b"x"
        ops.list_dir(CFG, "fs01/Documenti")
        assert ("fs02.estero.local", "ESTERO\\m.rossi") in smb.sessions
        assert ("fs01", "ACME\\mario") in smb.sessions

    def test_list_shares_groups_by_server(self, smb):
        r = ops.list_shares(CFG)
        assert [s["server"] for s in r["servers"]] == ["fs01", "fs02"]
        fs01 = r["servers"][0]
        assert fs01["label"] == "Sede"
        assert [s["path"] for s in fs01["shares"]] == ["fs01/Documenti", "fs01/Archivio"]
        assert fs01["shares"][1]["read_only"]
        assert smb.registered == 0  # served from the config, no network
        assert ops.list_shares(None)["error"] == "not_configured"

    def test_unknown_server(self, smb):
        assert ops.list_dir(CFG, "fs09/Documenti")["error"] == "server_not_allowed"

    def test_move_and_missing_file(self, smb):
        ops.write_text(CFG, "fs01/Documenti/a.txt", "1")
        assert ops.move(CFG, "fs01/Documenti/a.txt", "fs01/Documenti/b.txt")["ok"]
        assert ops.stat(CFG, "fs01/Documenti/a.txt")["error"] == "not_found"

    def test_list_and_search(self, smb):
        ops.mkdir(CFG, "fs01/Documenti/sub")
        ops.write_text(CFG, "fs01/Documenti/sub/report.txt", "r")
        names = [e["name"] for e in ops.list_dir(CFG, "fs01/Documenti")["entries"]]
        assert names == ["sub"]
        res = ops.search(CFG, "fs01/Documenti", "report")["results"]
        assert res[0]["path"] == "fs01/Documenti/sub/report.txt"

    def test_no_config_and_bad_path(self, smb):
        assert ops.list_dir(None, "fs01/Documenti")["error"] == "not_configured"
        assert ops.list_dir(CFG, "fs01/C$/x")["error"] == "share_not_allowed"

    def test_session_copy_and_upload(self, smb, monkeypatch, tmp_path):
        monkeypatch.setenv("AION_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("AION_CHAT_SESSION_ID", "sess-1234")
        ops.write_text(CFG, "fs01/Documenti/a.txt", "dati")
        c = ops.copy_to_session(CFG, "fs01/Documenti/a.txt")
        assert c["ok"] and c["session_path"] == "workspace/smb/a.txt"
        u = ops.upload_from_session(CFG, "fs01/Documenti/copy.txt", c["session_path"])
        assert u["ok"] and smb.fs["\\\\fs01\\Documenti\\copy.txt"] == b"dati"


class TestCredentialsAndGuard:
    """Scenario: no network without real credentials; one logon failure only."""

    def test_missing_credentials_no_network(self, smb, monkeypatch):
        monkeypatch.setenv("SMB_PASSWORD", "probe_secret_key")
        assert ops.list_dir(CFG, "fs01/Documenti")["error"] == "credentials_missing"
        assert smb.registered == 0

    def test_single_attempt_then_local_block(self, smb, monkeypatch):
        from smbprotocol.exceptions import LogonFailure

        calls = []

        def boom(*a, **k):
            calls.append(1)
            raise LogonFailure()

        monkeypatch.setattr("smbclient.register_session", boom)
        assert ops.list_dir(CFG, "fs01/Documenti")["error"] == "auth_failed"
        assert ops.list_dir(CFG, "fs01/Documenti")["error"] == "auth_failed"
        assert len(calls) == 1  # second call blocked locally
        monkeypatch.setenv("SMB_PASSWORD", "new-pw")
        ops.list_dir(CFG, "fs01/Documenti")
        assert len(calls) == 2  # new credentials -> retried

    def test_missing_extra_set_blocks_only_its_server(self, smb, monkeypatch):
        """Without the ESTERO pair fs02 fails locally while fs01 keeps working."""
        monkeypatch.delenv(EXTRA_ENV)
        r = ops.list_dir(CFG, "fs02/Documenti")
        assert r["error"] == "credentials_missing" and "ESTERO" in r["message"]
        assert smb.registered == 0
        assert ops.list_dir(CFG, "fs01/Documenti")["ok"]

    def test_logon_failure_blocks_only_its_set(self, smb, monkeypatch):
        """A wrong ESTERO password must not stop the DEFAULT servers."""
        from smbprotocol.exceptions import LogonFailure

        def register(host, username=None, **k):
            smb.sessions.append((host, username))
            if host == "fs02.estero.local":
                raise LogonFailure()

        monkeypatch.setattr("smbclient.register_session", register)
        assert ops.list_dir(CFG, "fs02/Documenti")["error"] == "auth_failed"
        assert ops.list_dir(CFG, "fs02/Documenti")["error"] == "auth_failed"
        assert ops.list_dir(CFG, "fs01/Documenti")["ok"]
        assert [h for h, _ in smb.sessions].count("fs02.estero.local") == 1

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
