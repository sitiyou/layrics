"""Right-click menu: item tree building and action dispatch.

The imgui menu inside the C++ core is a pure renderer; the item list and the
handling of clicked actions live here (Python side), mirroring `layctl dmenu`.
"""

import logging
import shutil
import subprocess

from .matching import clean_search_keyword

logger = logging.getLogger(__name__)


def notify(body: str, title: str = "layrics") -> None:
    """Show a desktop notification; fall back to the log when notify-send is missing."""
    if shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", "-a", "layrics", title, body],
                check=False,
                capture_output=True,
            )
            return
        except OSError:
            pass
    logger.info("%s: %s", title, body)


def _ass_config(app) -> dict:
    return app._config.get_provider_config("default")


def _fps_label(fps: int) -> str:
    return "跟随显示器" if fps == -1 else f"{fps} FPS"


async def _song_items(app) -> list[dict]:
    """Submenu items: search results for the current track; [] when unavailable."""
    if app.current_track is None:
        return []
    keyword = app.current_track.title or ""
    artists = app.current_track.artists or []
    if artists:
        keyword += " " + " ".join(artists)
    keyword = clean_search_keyword(keyword.strip())
    if not keyword:
        return []
    try:
        results = await app.search_songs(keyword, 20)
    except Exception as e:
        logger.warning("menu: song search failed: %s", e)
        return []
    items = []
    for c in results:
        label = c.get("title", "") or ""
        artists = c.get("artist") or []
        if artists:
            label += " - " + ", ".join(artists)
        album = c.get("album")
        if album:
            label += f" [{album}]"
        dur = c.get("duration")
        if dur and dur > 0:
            m, s = divmod(dur // 1000, 60)
            label += f" ({m}:{s:02d})"
        # Composite id (source prefix) so apply_cache_set can route the fetch.
        items.append({"label": label, "action": f"song:{c['source']}{c['id']}"})
    return items


async def build_menu(app) -> list[dict]:
    """Build the menu tree with current state baked into the labels."""
    prov = _ass_config(app)
    karaoke = prov.get("karaoke", True)
    line_mode = prov.get("line_mode") or "single"
    secondary = prov.get("secondary", True)
    s = app.ctrl.state

    song: list[dict] = await _song_items(app)
    players = app.list_players()
    player_name = "无"
    if app.mpris_player is not None:
        try:
            player_name = app.mpris_player.get_identity() or "?"
        except Exception:
            player_name = "?"

    items: list[dict] = []
    if song:
        items.append({"label": "搜索并设置歌词", "children": song})
    else:
        items.append({"label": "搜索并设置歌词（无当前曲目/结果）", "action": ""})
    items += [
        {"label": f"显示/隐藏（当前：{'隐藏' if s.hidden else '显示'}）", "action": "hide"},
        {"label": f"锁定（当前：{'已锁定' if s.locked else '未锁定'}）", "action": "lock"},
        {"label": f"卡拉OK（{'开' if karaoke else '关'}）", "action": "karaoke"},
        {
            "label": f"歌词模式（{'双行' if line_mode == 'double' else '单行'}）",
            "action": "line_mode",
        },
        {"label": f"翻译（{'开' if secondary else '关'}）", "action": "secondary"},
        {
            "label": f"帧率（当前：{_fps_label(s.target_fps)}）",
            "children": [
                {"label": "跟随显示器 (vsync)", "action": "fps:-1"},
                {"label": "30 FPS", "action": "fps:30"},
                {"label": "60 FPS", "action": "fps:60"},
                {"label": "120 FPS", "action": "fps:120"},
            ],
        },
    ]
    if players:
        items.append(
            {
                "label": f"播放器（当前：{player_name}）",
                "children": [
                    {"label": f"{identity} ({bus})", "action": f"player:{bus}"}
                    for bus, identity in players
                ],
            }
        )
    else:
        items.append({"label": "播放器（无可选）", "action": ""})
    items += [
        {
            "label": "缓存管理",
            "children": [
                {"label": "查看缓存", "action": "cache:list"},
                {"label": "删除当前曲目缓存", "action": "cache:remove"},
            ],
        },
        {"label": "显示状态", "action": "status"},
        {"label": "退出", "action": "quit"},
    ]
    return items


def _cache_summary(app) -> str:
    from .cache import SongCache

    entries = SongCache().list_all()
    if not entries:
        return "缓存为空"
    lines = []
    for e in entries[:5]:
        title = e.get("lyrics_title") or ""
        artists = e.get("lyrics_artists") or []
        artist_str = (
            ", ".join(artists) if isinstance(artists, list) else str(artists)
        )
        lines.append(f"{e['key']} -> {e.get('song_id', '')} {title} {artist_str}".rstrip())
    if len(entries) > 5:
        lines.append(f"... 共 {len(entries)} 条")
    return "\n".join(lines)


def _status_lines(app) -> str:
    player = None
    if app.mpris_player is not None:
        try:
            player = {
                "identity": app.mpris_player.get_identity(),
                "bus_name": app.mpris_player.bus_name,
                "playback_status": app.mpris_player.get_playback_status(),
                "position_ms": app.mpris_player.get_position() // 1000,
                "track": app.current_track,
            }
        except Exception:
            player = {"error": "disconnected"}
    s = app.ctrl.state
    lines = []
    if not player:
        lines.append("播放器: 无")
    else:
        lines.append(f"播放器: {player.get('identity', '?')} ({player.get('bus_name', '?')})")
        lines.append(f"状态: {player.get('playback_status', '?')}")
        pos = player.get("position_ms")
        if isinstance(pos, int):
            lines.append(f"进度: {pos // 60000}:{(pos // 1000) % 60:02d}")
        track = player.get("track")
        if track:
            title = track.title or ""
            if title:
                artists = track.artists or []
                suffix = f" - {', '.join(artists)}" if artists else ""
                lines.append(f"曲目: {title}{suffix}")
    lines.append("")
    lines.append(f"隐藏: {'是' if s.hidden else '否'}")
    lines.append(f"锁定: {'是' if s.locked else '否'}")
    lines.append(f"暂停: {'是' if s.paused else '否'}")
    lines.append(f"帧率: {_fps_label(s.target_fps)}")
    return "\n".join(lines)


async def handle_action(app, action: str) -> None:
    """Dispatch a menu action; the heavy lifting lives on LayricsApp methods."""
    try:
        if action == "quit":
            app.quit()
        elif action == "hide":
            app.ctrl.set_status(hidden=not app.ctrl.state.hidden)
        elif action == "lock":
            app.ctrl.set_status(locked=not app.ctrl.state.locked)
        elif action in ("karaoke", "line_mode", "secondary"):
            await app.apply_ass_config(action, "toggle")
        elif action.startswith("fps:"):
            app.apply_target_fps(int(action[len("fps:"):]))
        elif action.startswith("player:"):
            app.select_mpris_player(action[len("player:"):])
        elif action.startswith("song:"):
            await app.apply_cache_set(action[len("song:"):])
        elif action == "cache:list":
            notify(_cache_summary(app), "layrics 缓存")
        elif action == "cache:remove":
            app.apply_cache_remove()
        elif action == "status":
            notify(_status_lines(app), "layrics 状态")
        else:
            logger.warning("unknown ui action: %s", action)
    except Exception:
        logger.exception("ui action failed: %s", action)
