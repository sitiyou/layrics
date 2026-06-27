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
        "--socket",
        "-s",
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
    """Show overlay and player status"""
    _pp(_call(ctx.obj["socket"], "get_status"))


@cli.command(name="players")
@click.pass_context
def list_players(ctx):
    """List available MPRIS players"""
    _pp(_call(ctx.obj["socket"], "list_players"))


@cli.command(name="set-player")
@click.argument("name")
@click.pass_context
def select_player(ctx, name: str):
    """Select MPRIS player by D-Bus bus name (e.g. org.mpris.MediaPlayer2.mpd)"""
    _pp(_call(ctx.obj["socket"], "select_player", {"name": name}))


@cli.command()
@click.argument("keyword")
@click.option("--limit", "-l", default=10, help="Max results", show_default=True)
@click.pass_context
def search(ctx, keyword: str, limit: int):
    """Search songs by keyword across all sources"""
    _pp(_call(ctx.obj["socket"], "search_songs", {"keyword": keyword, "limit": limit}))


@cli.command()
@click.argument("song_id", required=False, default="")
@click.pass_context
def fetch(ctx, song_id: str):
    """Fetch ASS content for a song or current track"""
    params: dict[str, Any] = {}
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
    """Load an ASS file and display on overlay"""
    _pp(_call(ctx.obj["socket"], "load_ass", {"path": path}))


@cli.command()
@click.argument("value", required=False)
@click.pass_context
def hide(ctx, value: str | None = None):
    """Hide the overlay (optional: 1/0/true/false/on/off/yes/no/toggle)"""
    params = {"value": value} if value is not None else {}
    _pp(_call(ctx.obj["socket"], "hide", params))


@cli.command()
@click.pass_context
def unhide(ctx):
    """Unhide the overlay"""
    _pp(_call(ctx.obj["socket"], "unhide"))


@cli.command()
@click.argument("value", required=False)
@click.pass_context
def lock(ctx, value: str | None = None):
    """Lock overlay (optional: 1/0/true/false/on/off/yes/no/toggle)"""
    params = {"value": value} if value is not None else {}
    _pp(_call(ctx.obj["socket"], "lock", params))


@cli.command()
@click.pass_context
def unlock(ctx):
    """Unlock overlay (allow interaction)"""
    _pp(_call(ctx.obj["socket"], "unlock"))


@cli.command(name="set-fps", context_settings=dict(ignore_unknown_options=True))
@click.argument("fps", type=int)
@click.pass_context
def set_fps(ctx, fps: int):
    """Set target frame rate (-1 for vsync)"""
    _pp(_call(ctx.obj["socket"], "set_fps", {"fps": fps}))


@cli.command()
@click.pass_context
def stop(ctx):
    """Stop the overlay process"""
    _pp(_call(ctx.obj["socket"], "stop"))


@cli.command()
@click.pass_context
def start(ctx):
    """Start the overlay process"""
    _pp(_call(ctx.obj["socket"], "start"))


@cli.command(name="set-lrc")
@click.argument("song_id")
@click.pass_context
def set_lrc(ctx, song_id: str):
    """Set lyrics for current track and update cache"""
    _pp(_call(ctx.obj["socket"], "cache_set", {"song_id": song_id}))


@cli.command()
@click.pass_context
def dmenu(ctx):
    """Search current playing song, output dmenu-compatible lines"""
    status = _call(ctx.obj["socket"], "get_status")
    if status.get("type") == "error":
        _pp(status)
        return
    track = status.get("data", {}).get("mpris_player", {}).get("track")
    if not track:
        click.echo("Error: no current track", err=True)
        sys.exit(1)
    keyword = track.get("title", "") or ""
    artists = track.get("artists") or []
    if artists:
        keyword += " " + " ".join(artists)
    keyword = keyword.strip()
    if not keyword:
        click.echo("Error: empty keyword from current track", err=True)
        sys.exit(1)
    results = _call(
        ctx.obj["socket"], "search_songs", {"keyword": keyword, "limit": 20}
    )
    if results.get("type") == "error":
        _pp(results)
        return
    for c in results.get("data", []):
        name = c.get("name", "")
        artists_str = ", ".join(c.get("artists", []))
        dur = c.get("duration")
        dur_str = ""
        if dur and dur > 0:
            m, s = divmod(dur // 1000, 60)
            dur_str = f"{m}:{s:02d}"
        album = c.get("album", "")
        click.echo(f"{c['id']}\t{dur_str}\t{name}\t{artists_str}\t{album}")


@cli.group()
@click.pass_context
def cache(ctx):
    """Manage song-to-lyrics cache"""


@cache.command(name="list")
@click.pass_context
def cache_list(ctx):
    """List all cached song-to-lyrics mappings"""
    _pp(_call(ctx.obj["socket"], "cache_list"))


@cache.command(name="set")
@click.argument("song_id")
@click.option("--key", default="", help="Cache key (defaults to current track)")
@click.pass_context
def cache_set(ctx, song_id: str, key: str):
    """Cache a song-to-lyrics mapping"""
    params: dict[str, Any] = {"song_id": song_id}
    if key:
        params["key"] = key
    _pp(_call(ctx.obj["socket"], "cache_set", params))


@cache.command(name="remove")
@click.option("--key", default="", help="Cache key (defaults to current track)")
@click.pass_context
def cache_remove(ctx, key: str):
    """Remove a cached song-to-lyrics mapping"""
    params: dict[str, Any] = {}
    if key:
        params["key"] = key
    _pp(_call(ctx.obj["socket"], "cache_remove", params))


@cli.command()
@click.argument("key")
@click.argument("value")
@click.pass_context
def ass(ctx, key: str, value: str):
    """Set ASS renderer config (karaoke, line_mode, secondary)"""
    _pp(_call(ctx.obj["socket"], "ass_set", {"key": key, "value": value}))


if __name__ == "__main__":
    cli()
