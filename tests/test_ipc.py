import asyncio
import io
import json
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock, call

import click
import pytest
from click.testing import CliRunner

from layrics.layctl import _send, cli
from layrics.main import LayricsApp


@pytest.fixture
def ipc_server(tmp_path):
    @contextmanager
    def serve(chunks):
        path = str(tmp_path / "ipc.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.settimeout(5)
            listener.bind(path)
            listener.listen(1)

            def reply():
                conn, _ = listener.accept()
                with conn, conn.makefile("rb") as reader:
                    conn.settimeout(5)
                    request = json.loads(reader.readline())
                    for chunk in chunks:
                        conn.sendall(chunk)
                        time.sleep(0.01)
                    return request

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(reply)
                yield path, future
                future.result(timeout=5)

    return serve


@pytest.mark.parametrize("ass", ["短い歌詞\n", "歌詞\n" * 100000])
def test_fetch_reads_complete_fragmented_response(ipc_server, ass):
    response = {"id": 1, "type": "result", "data": {"ass": ass}}
    payload = (json.dumps(response, ensure_ascii=False) + "\n").encode()
    split = payload.index("歌".encode()) + 1
    with ipc_server([payload[:split], payload[split:]]) as (path, request):
        result = CliRunner().invoke(cli, ["--socket", path, "fetch", "QM123"])
        assert result.exit_code == 0, result.output
        assert result.output == ass + "\n"
        assert request.result(timeout=5) == {
            "id": 1,
            "method": "fetch_lyrics",
            "params": {"song_id": "QM123"},
        }


@pytest.mark.parametrize("payload", [b"", b'{"id": 1', b'{"id": 1}'])
def test_send_reports_incomplete_response(ipc_server, payload):
    with (
        ipc_server([payload]) as (path, _),
        pytest.raises(click.ClickException, match="before a complete response"),
    ):
        _send(path, {"id": 1, "method": "get_status"})


def test_send_waits_for_response_without_request_timeout(monkeypatch):
    sock = Mock()
    sock.makefile.return_value = io.BytesIO(b'{"id": 1}\n')
    monkeypatch.setattr(socket, "socket", Mock(return_value=sock))
    assert _send("ipc.sock", {"id": 1}) == {"id": 1}
    assert sock.settimeout.call_args_list == [call(10), call(None)]
    sock.connect.assert_called_once_with("ipc.sock")
    sock.close.assert_called_once_with()


@pytest.mark.parametrize("stage", ["readline", "write", "drain", "wait_closed"])
@pytest.mark.parametrize("error", [ConnectionResetError, BrokenPipeError])
def test_handle_client_accepts_disconnect(stage, error):
    app = object.__new__(LayricsApp)
    app._execute = AsyncMock(return_value={"id": 1, "type": "result", "data": {}})
    reader = Mock()
    reader.readline = AsyncMock(return_value=b'{"id": 1, "method": "get_status"}\n')
    writer = Mock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    target = reader if stage == "readline" else writer
    getattr(target, stage).side_effect = error("client disconnected")

    asyncio.run(app._handle_client(reader, writer))

    writer.close.assert_called_once_with()
    writer.wait_closed.assert_awaited_once_with()
    assert writer.write.call_count == (0 if stage == "readline" else 1)
