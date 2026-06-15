import json
import os
import socket
import sys
from typing import Any, Optional

import click

SOCKET_PATH = os.environ.get(
    "LAYRICS_SOCK",
    os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "layrics.sock"),
)

_common_params = [
    click.option(
        "--socket", "-s",
        default=SOCKET_PATH,
        envvar="LAYRICS_SOCK",
        help="IPC socket path",
        show_default=True,
    ),
]


def common_options(f):
    for opt in reversed(_common_params):
        f = opt(f)
    return f


def _send(socket_path: str, body: dict) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(10)
    try:
        s.connect(socket_path)
        s.sendall((json.dumps(body) + "\n").encode())
        resp = s.recv(65536)
    finally:
        s.close()
    return json.loads(resp.decode())


def _call(socket_path: str, method: str, params: Optional[dict] = None) -> dict:
    return _send(socket_path, {"id": 1, "method": method, "params": params or {}})


def _pp(result: dict):
    typ = result.get("type")
    if typ == "error":
        data = result.get("data", {})
        click.echo(f"Error [{data.get('code', '?')}]: {data.get('message', 'unknown')}")
        sys.exit(1)
    click.echo(json.dumps(result.get("data", {}), ensure_ascii=False, indent=2))


# ── commands ────────────────────────────────────────────────────────


@click.group()
@common_options
@click.pass_context
def cli(ctx: click.Context, socket: str):
    ctx.ensure_object(dict)
    ctx.obj["socket"] = socket


@cli.command()
@click.pass_context
def status(ctx):
    _pp(_call(ctx.obj["socket"], "get_status"))


@cli.command(name="list-players")
@click.pass_context
def list_players(ctx):
    _pp(_call(ctx.obj["socket"], "list_players"))


@cli.command(name="select-player")
@click.argument("name")
@click.pass_context
def select_player(ctx, name: str):
    _pp(_call(ctx.obj["socket"], "select_player", {"name": name}))


@cli.command()
@click.argument("keyword")
@click.option("--limit", "-l", default=10, help="Max results", show_default=True)
@click.pass_context
def search(ctx, keyword: str, limit: int):
    _pp(_call(ctx.obj["socket"], "search_songs", {"keyword": keyword, "limit": limit}))


@cli.command()
@click.argument("song_id", required=False, default="")
@click.option("--sync", is_flag=True, help="Also update overlay with fetched lyrics")
@click.pass_context
def fetch(ctx, song_id: str, sync: bool):
    params = {"sync": sync}
    if song_id:
        params["song_id"] = song_id
    resp = _call(ctx.obj["socket"], "fetch_lyrics", params)
    if resp.get("type") == "error":
        _pp(resp)
        return
    data = resp.get("data", {})
    ass = data.get("ass", "")
    click.echo(ass)


@cli.command()
@click.argument("path")
@click.pass_context
def load(ctx, path: str):
    _pp(_call(ctx.obj["socket"], "load_ass", {"path": path}))


@cli.command()
@click.pass_context
def hide(ctx):
    _pp(_call(ctx.obj["socket"], "hide"))


@cli.command()
@click.pass_context
def unhide(ctx):
    _pp(_call(ctx.obj["socket"], "unhide"))


@cli.command()
@click.pass_context
def lock(ctx):
    _pp(_call(ctx.obj["socket"], "lock"))


@cli.command()
@click.pass_context
def unlock(ctx):
    _pp(_call(ctx.obj["socket"], "unlock"))


@cli.command()
@click.pass_context
def stop(ctx):
    _pp(_call(ctx.obj["socket"], "stop"))


@cli.command()
@click.pass_context
def start(ctx):
    _pp(_call(ctx.obj["socket"], "start"))


if __name__ == "__main__":
    cli()
