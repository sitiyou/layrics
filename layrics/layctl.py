import json
import os
import socket
import sys
from typing import Any

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


def _call(socket_path: str, method: str, params: dict | None = None) -> dict:
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
    """List available sources (MPRIS players / MPD)"""
    _pp(_call(ctx.obj["socket"], "list_players"))


@cli.command(name="set-player")
@click.argument("name")
@click.pass_context
def select_player(ctx, name: str):
    """Pin a source by id (an MPRIS bus name, "mpd", or "auto")"""
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


@cli.command(name="set-fps", context_settings={"ignore_unknown_options": True})
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


def _resolve_menu_program(override: str | None) -> str:
    """菜单程序优先级：--program > LAYRICS_DMENU > [dmenu] program > "dmenu"""
    if override:
        return override
    env = os.environ.get("LAYRICS_DMENU")
    if env:
        return env
    try:
        from .config import get_config

        program = get_config().dmenu.program
    except ImportError, OSError, ValueError:
        return "dmenu"
    return program or "dmenu"


def _run_menu(program: str, prompt: str, items: list[str]) -> str | None:
    """调用菜单程序展示 items（每行一个），返回选中行；用户取消（ESC）返回 None。"""
    if not items:
        return None
    import shlex
    import subprocess

    cmd = shlex.split(program)
    if not cmd:
        click.echo(f"Error: empty menu program: {program!r}", err=True)
        sys.exit(1)
    if os.path.basename(cmd[0]) in ("dmenu", "rofi"):
        cmd += ["-p", prompt]
    try:
        proc = subprocess.run(
            cmd,
            input="\n".join(items) + "\n",
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        click.echo(
            f"Error: menu program not found: {program!r} "
            "(install it or set [dmenu] program / LAYRICS_DMENU)",
            err=True,
        )
        sys.exit(1)
    if proc.returncode != 0:
        return None
    picked = proc.stdout.strip()
    return picked or None


def _menu_select(program: str, prompt: str, items: list[tuple[str, str]]) -> str | None:
    """items: [(label, action)]，展示带序号菜单并返回选中项的 action；取消返回 None。

    菜单行只含 label（`N) label`），action 通过行首序号反查，避免 action 显示在菜单中。
    """
    picked = _run_menu(
        program,
        prompt,
        [f"{i}) {label}" for i, (label, _) in enumerate(items, 1)],
    )
    if picked is None:
        return None
    # 按行首序号定位 action（菜单程序返回完整选中行）
    if ")" in picked:
        head = picked.split(")", 1)[0].strip()
        if head.isdigit():
            idx = int(head)
            if 1 <= idx <= len(items):
                return items[idx - 1][1]
    # 兜底：按 label 匹配（兼容菜单程序对选中行的裁剪）
    for label, action in items:
        if picked in label or label in picked:
            return action
    return None


def _menu_song(sock: str, prog: str) -> None:
    """子菜单：用当前曲目关键词搜索歌曲，选择后 cache_set。"""
    status = _call(sock, "get_status")
    if status.get("type") == "error":
        _pp(status)
        return
    track = status.get("data", {}).get("player", {}).get("track")
    if not track:
        click.echo("No current track", err=True)
        return
    keyword = track.get("title", "") or ""
    artists = track.get("artists") or []
    if artists:
        keyword += " " + " ".join(artists)
    keyword = keyword.strip()
    if not keyword:
        click.echo("Current track has no title", err=True)
        return
    results = _call(sock, "search_songs", {"keyword": keyword, "limit": 20})
    if results.get("type") == "error":
        _pp(results)
        return
    cands = results.get("data", [])
    if not cands:
        click.echo("No search results", err=True)
        return
    items = []
    for c in cands:
        name = c.get("title", "")
        artists_str = ", ".join(c.get("artist") or [])
        album = c.get("album", "")
        dur = c.get("duration")
        dur_str = ""
        if dur and dur > 0:
            m, s = divmod(dur // 1000, 60)
            dur_str = f"{m}:{s:02d}"
        label = name
        if artists_str:
            label += f" - {artists_str}"
        if album:
            label += f" [{album}]"
        if dur_str:
            label += f" ({dur_str})"
        label += f" [{c['id']}]"
        items.append((label, f"song:{c['id']}"))
    picked = _menu_select(prog, "Select lyrics", items)
    if picked and picked.startswith("song:"):
        song_id = picked[len("song:") :]
        _call(sock, "cache_set", {"song_id": song_id})


def _menu_fps(sock: str, prog: str) -> None:
    """子菜单：选择目标帧率。"""
    items = [
        ("Follow display (vsync)", "fps:-1"),
        ("30 FPS", "fps:30"),
        ("60 FPS", "fps:60"),
        ("120 FPS", "fps:120"),
    ]
    picked = _menu_select(prog, "Select FPS", items)
    if picked and picked.startswith("fps:"):
        _call(sock, "set_fps", {"fps": int(picked[len("fps:") :])})


def _menu_player(sock: str, prog: str) -> None:
    """子菜单：选择跟随的播放源。"""
    resp = _call(sock, "list_players")
    if resp.get("type") == "error":
        _pp(resp)
        return
    players = resp.get("data", [])
    items = [("Auto (follow the playing source)", "player:auto")]
    for p in players:
        identity = p.get("identity") or p.get("id") or "?"
        items.append((f"{identity} ({p['id']})", f"player:{p['id']}"))
    picked = _menu_select(prog, "Select source", items)
    if picked and picked.startswith("player:"):
        _call(sock, "select_player", {"name": picked[len("player:") :]})


def _notify(body: str, title: str = "layrics") -> None:
    """通过 notify-send 展示通知；notify-send 不可用时回退到终端输出。"""
    import shutil
    import subprocess

    if not shutil.which("notify-send"):
        click.echo(body)
        return
    try:
        subprocess.run(
            ["notify-send", "-a", "layrics", title, body],
            check=False,
            capture_output=True,
        )
    except OSError:
        click.echo(body)


def _menu_cache(sock: str, prog: str) -> None:
    """子菜单：缓存列表 / 删除当前曲目缓存。"""
    items = [
        ("List cache", "cache:list"),
        ("Remove current track cache", "cache:remove"),
    ]
    picked = _menu_select(prog, "Cache management", items)
    if picked == "cache:list":
        resp = _call(sock, "cache_list")
        if resp.get("type") == "error":
            _pp(resp)
            return
        entries = resp.get("data", [])
        if not entries:
            _notify("Cache is empty", "layrics cache")
            return
        lines = []
        for e in entries[:5]:
            title = e.get("lyrics_title") or ""
            artists = e.get("lyrics_artists") or []
            artist_str = (
                ", ".join(artists) if isinstance(artists, list) else str(artists)
            )
            src = e.get("song_id", "")
            lines.append(f"{e['key']} -> {src} {title} {artist_str}".rstrip())
        if len(entries) > 5:
            lines.append(f"... total {len(entries)} entries")
        _notify("\n".join(lines), "layrics cache")
    elif picked == "cache:remove":
        resp = _call(sock, "cache_remove", {})
        if resp.get("type") == "error":
            _pp(resp)
            return
        _notify("Removed current track cache", "layrics cache")


def _print_status(sock: str, status: dict | None = None) -> None:
    """格式化 get_status 结果，通过 notify-send 展示。"""
    if status is None:
        status = _call(sock, "get_status")
    if status.get("type") == "error":
        _pp(status)
        return
    data = status.get("data", {})
    player = data.get("player") or {}
    overlay = data.get("overlay", {})
    lines = []
    if not player:
        lines.append("Player: none")
    elif player.get("error"):
        lines.append("Player: disconnected")
    else:
        pinned = " pinned" if player.get("pinned") else ""
        lines.append(
            f"Player: {player.get('identity', '?')} ({player.get('id', '?')}){pinned}"
        )
        lines.append(f"Status: {player.get('playback_status', '?')}")
        pos = player.get("position_ms")
        if isinstance(pos, int):
            lines.append(f"Position: {pos // 60000}:{(pos // 1000) % 60:02d}")
        track = player.get("track") or {}
        title = track.get("title")
        if title:
            artists = track.get("artists") or []
            suffix = f" - {', '.join(artists)}" if artists else ""
            lines.append(f"Track: {title}{suffix}")
    lines.append("")
    lines.append(f"Hidden: {'yes' if overlay.get('hidden') else 'no'}")
    lines.append(f"Locked: {'yes' if overlay.get('locked') else 'no'}")
    lines.append(f"Paused: {'yes' if overlay.get('paused') else 'no'}")
    lines.append(f"FPS: {overlay.get('target_fps')}")
    lines.append(f"Position: {overlay.get('position_ms')} ms")
    _notify("\n".join(lines), "layrics status")


@cli.command()
@click.option(
    "--program",
    default=None,
    help="menu program (overrides [dmenu] program / LAYRICS_DMENU)",
)
@click.pass_context
def dmenu(ctx, program: str | None):
    """Interactive menu: songs / visibility / lock / ASS config / FPS / player / cache / status"""
    sock = ctx.obj["socket"]
    prog = _resolve_menu_program(program)

    status = _call(sock, "get_status")
    if status.get("type") == "error":
        _pp(status)
        return
    data = status.get("data", {})
    overlay = data.get("overlay", {})
    player = data.get("player") or {}

    ass_cfg = _call(sock, "ass_get")
    ass = ass_cfg.get("data", {}) if ass_cfg.get("type") == "result" else {}

    hidden = bool(overlay.get("hidden"))
    locked = bool(overlay.get("locked"))
    karaoke = ass.get("karaoke")
    karaoke = True if karaoke is None else bool(karaoke)
    line_mode = ass.get("line_mode") or "single"
    secondary = ass.get("secondary")
    secondary = True if secondary is None else bool(secondary)
    fps = overlay.get("target_fps", -1)
    fps_str = "vsync" if fps == -1 else f"{fps} FPS"
    player_name = player.get("identity") or player.get("id") or "none"

    items = [
        ("Search & set lyrics", "song"),
        (f"Toggle visibility ({'hidden' if hidden else 'shown'})", "hide"),
        (f"Toggle lock ({'on' if locked else 'off'})", "lock"),
        (f"Toggle karaoke ({'on' if karaoke else 'off'})", "karaoke"),
        (
            f"Toggle line mode ({'double' if line_mode == 'double' else 'single'})",
            "line_mode",
        ),
        (f"Toggle translation ({'on' if secondary else 'off'})", "secondary"),
        (f"Set FPS (current: {fps_str})", "fps"),
        (f"Select player (current: {player_name})", "player"),
        ("Cache management", "cache"),
        ("Show status", "status"),
        ("Quit", "quit"),
    ]
    action = _menu_select(prog, "layrics", items)
    if action is None or action == "quit":
        return
    if action == "song":
        _menu_song(sock, prog)
    elif action == "hide":
        _call(sock, "hide", {"value": "toggle"})
    elif action == "lock":
        _call(sock, "lock", {"value": "toggle"})
    elif action in ("karaoke", "line_mode", "secondary"):
        _call(sock, "ass_set", {"key": action, "value": "toggle"})
    elif action == "fps":
        _menu_fps(sock, prog)
    elif action == "player":
        _menu_player(sock, prog)
    elif action == "cache":
        _menu_cache(sock, prog)
    elif action == "status":
        _print_status(sock, status)


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


@cli.command(name="ass-get")
@click.pass_context
def ass_get(ctx):
    """Show current ASS renderer config (karaoke, line_mode, secondary)"""
    _pp(_call(ctx.obj["socket"], "ass_get"))


if __name__ == "__main__":
    cli()
