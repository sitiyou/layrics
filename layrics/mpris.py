#!/usr/bin/env python3
"""
MPRIS (Media Player Remote Interfacing Specification) 实现
用于从 Linux 音乐播放器获取歌曲元数据
"""

import json
import os
import sys
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)


@dataclass
class TrackMeta:
    """歌曲元数据结构"""

    unique_song_id: Optional[str] = None
    title: Optional[str] = None
    album: Optional[str] = None
    artists: Optional[List[str]] = None
    length: Optional[int] = None  # 微秒

    def __repr__(self):
        return (
            f"TrackMeta(\n"
            f"  title={self.title!r},\n"
            f"  album={self.album!r},\n"
            f"  artists={self.artists!r},\n"
            f"  length={self.length}μs,\n"
            f"  song_id={self.unique_song_id!r}\n"
            f")"
        )


class MPRISPlayer:
    """MPRIS 播放器接口"""

    # MPRIS 接口前缀
    MPRIS_PREFIX = "org.mpris.MediaPlayer2"

    def __init__(self, bus_name: str):
        """初始化 MPRIS 播放器连接

        Args:
            bus_name: D-Bus 总线名称，例如 "org.mpris.MediaPlayer2.spotify"
        """
        self.bus_name = bus_name
        self.bus = dbus.SessionBus()

        try:
            self.obj = self.bus.get_object(bus_name, "/org/mpris/MediaPlayer2")
            self.properties_interface = dbus.Interface(
                self.obj, dbus_interface="org.freedesktop.DBus.Properties"
            )
        except dbus.DBusException as e:
            raise ConnectionError(f"无法连接到播放器 {bus_name}: {e}")

    def get_metadata(self) -> TrackMeta:
        metadata = self.properties_interface.Get(
            "org.mpris.MediaPlayer2.Player", "Metadata"
        )
        return self._parse_metadata(metadata)

    def get_position(self) -> int:
        return int(
            self.properties_interface.Get("org.mpris.MediaPlayer2.Player", "Position")
        )

    def get_playback_status(self) -> str:
        return str(
            self.properties_interface.Get(
                "org.mpris.MediaPlayer2.Player", "PlaybackStatus"
            )
        )

    def get_identity(self) -> str:
        """获取播放器名称"""
        try:
            return str(
                self.properties_interface.Get("org.mpris.MediaPlayer2", "Identity")
            )
        except dbus.DBusException as e:
            print(f"获取播放器名称失败: {e}", file=sys.stderr)
            return self.bus_name

    @staticmethod
    def _parse_metadata(metadata: Dict[str, Any]) -> TrackMeta:
        """解析 MPRIS 元数据字典

        MPRIS 元数据键值:
        - mpris:trackid: 曲目 ID
        - xesam:title: 歌曲标题
        - xesam:album: 专辑名称
        - xesam:artist: 艺术家 (列表)
        - mpris:length: 歌曲长度 (微秒)
        """

        def get_str(key: str) -> Optional[str]:
            """安全获取字符串值"""
            val = metadata.get(key)
            if val is not None:
                return str(val)
            return None

        def get_list_str(key: str) -> Optional[List[str]]:
            """安全获取字符串列表"""
            val = metadata.get(key)
            if val:
                return [str(v) for v in val]
            return None

        # 提取 track_id (可能包含完整路径，通常需要取最后部分)
        track_id = get_str("mpris:trackid")
        if track_id and "/" in track_id:
            track_id = track_id.split("/")[-1]

        # 提取长度 (转换为微秒整数)
        length = None
        length_val = metadata.get("mpris:length")
        if length_val is not None:
            try:
                length = int(length_val)
            except (ValueError, TypeError):
                length = None

        return TrackMeta(
            unique_song_id=track_id,
            title=get_str("xesam:title"),
            album=get_str("xesam:album"),
            artists=get_list_str("xesam:artist"),
            length=length,
        )


class MPRISPlayerFinder:
    """MPRIS 播放器查找器"""

    def __init__(self):
        self.bus = dbus.SessionBus()

    @staticmethod
    def _is_mpris_player(name: str) -> bool:
        """检查是否是 MPRIS 播放器"""
        return name.startswith(MPRISPlayer.MPRIS_PREFIX)

    def find_all_players(self) -> List[MPRISPlayer]:
        """发现所有可用的 MPRIS 播放器"""
        players = []

        try:
            # 获取总线上的所有服务名
            dbus_obj = self.bus.get_object(
                "org.freedesktop.DBus", "/org/freedesktop/DBus"
            )
            dbus_interface = dbus.Interface(
                dbus_obj, dbus_interface="org.freedesktop.DBus"
            )
            names = dbus_interface.ListNames()

            # 过滤 MPRIS 播放器
            for name in names:
                if self._is_mpris_player(name):
                    try:
                        player = MPRISPlayer(name)
                        players.append(player)
                    except ConnectionError as e:
                        print(f"警告: {e}", file=sys.stderr)

        except dbus.DBusException as e:
            print(f"列出 D-Bus 服务失败: {e}", file=sys.stderr)

        return players

    def find_active_player(self) -> Optional[MPRISPlayer]:
        """查找活跃的播放器 (正在播放的)"""
        players = self.find_all_players()

        for player in players:
            try:
                status = player.get_playback_status()
                if status == "Playing":
                    return player
            except Exception as e:
                print(f"检查播放器状态失败: {e}", file=sys.stderr)

        # 如果没有正在播放的，返回第一个
        return players[0] if players else None

    def list_player_names(self) -> List[tuple]:
        """列出所有播放器的名称

        Returns:
            List of (bus_name, identity)
        """
        result = []
        for player in self.find_all_players():
            try:
                result.append((player.bus_name, player.get_identity()))
            except Exception:
                pass
        return result


class MprisSignalMonitor:
    """Receive MPRIS player signals via a dedicated GLib thread.

    Communicates back to the caller via a self-pipe (async-signal-safe).
    Events are encoded as newline-delimited JSON::

        {"type":"status","value":"Playing"}
        {"type":"status","value":"Paused"}
        {"type":"status","value":"Stopped"}
        {"type":"seeked","value":12345678}
        {"type":"track","value":"spotify:track:..."}
    """

    def __init__(self, bus_name: str):
        self.bus_name = bus_name
        self._r_fd, self._w_fd = os.pipe()
        self._loop: Optional[GLib.MainLoop] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._loop = GLib.MainLoop()

        bus = dbus.SessionBus()
        obj = bus.get_object(self.bus_name, "/org/mpris/MediaPlayer2")

        obj.connect_to_signal(
            "PropertiesChanged",
            self._on_properties_changed,
            dbus_interface="org.freedesktop.DBus.Properties",
        )
        obj.connect_to_signal(
            "Seeked",
            self._on_seeked,
            dbus_interface="org.mpris.MediaPlayer2.Player",
        )

        self._loop.run()

    def _emit(self, data: str):
        try:
            os.write(self._w_fd, (data + "\n").encode())
        except OSError:
            pass

    def _on_properties_changed(self, interface: str, changed: dict, invalidated: dict):
        if interface != "org.mpris.MediaPlayer2.Player":
            return
        if "PlaybackStatus" in changed:
            self._emit(
                json.dumps({"type": "status", "value": str(changed["PlaybackStatus"])})
            )
        if "Metadata" in changed:
            mdata = changed["Metadata"]
            tid = mdata.get("mpris:trackid", "")
            if tid and "/" in tid:
                tid = tid.split("/")[-1]
            self._emit(json.dumps({"type": "track", "value": tid}))

    def _on_seeked(self, position: dbus.Int64):
        self._emit(json.dumps({"type": "seeked", "value": int(position)}))

    def fileno(self) -> int:
        """File descriptor for asyncio ``add_reader``."""
        return self._r_fd

    def read_events(self):
        """Yield parsed events from the pipe."""
        try:
            raw = os.read(self._r_fd, 65536)
        except OSError:
            return
        for line in raw.decode().strip().split("\n"):
            if line:
                yield json.loads(line)

    def stop(self):
        if self._loop:
            self._loop.quit()
        os.close(self._r_fd)
        os.close(self._w_fd)


def demo_basic():
    """基础演示: 获取当前歌曲元数据"""
    print("=" * 60)
    print("MPRIS 歌曲元数据获取演示")
    print("=" * 60)

    # 初始化 D-Bus
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    # 查找播放器
    finder = MPRISPlayerFinder()
    players = finder.find_all_players()

    if not players:
        print("未找到任何 MPRIS 播放器")
        return

    print(f"\n发现 {len(players)} 个播放器:")
    for bus_name, identity in finder.list_player_names():
        print(f"  - {identity} ({bus_name})")

    # 获取活跃播放器的元数据
    player = finder.find_active_player()
    if player:
        print(f"\n连接到: {player.get_identity()}")
        print(f"播放状态: {player.get_playback_status()}")
        print(f"播放位置: {player.get_position() / 1_000_000:.2f}s")

        metadata = player.get_metadata()
        print(f"\n歌曲元数据:\n{metadata}")


def demo_monitor():
    """监听模式演示: 实时监听元数据变化"""
    print("\n" + "=" * 60)
    print("监听歌曲切换演示 (按 Ctrl+C 退出)")
    print("=" * 60)

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    finder = MPRISPlayerFinder()
    player = finder.find_active_player()

    if not player:
        print("未找到活跃播放器")
        return

    print(f"监听播放器: {player.get_identity()}\n")

    # 获取初始元数据
    last_metadata = None

    def on_properties_changed(interface, changed, invalidated):
        """D-Bus 属性变化回调"""
        nonlocal last_metadata

        if "Metadata" in changed:
            metadata = player.get_metadata()
            if metadata != last_metadata:
                print(f"[歌曲切换]\n{metadata}\n")
                last_metadata = metadata

    try:
        # 订阅属性变化信号
        player.obj.connect_to_signal(
            "PropertiesChanged",
            on_properties_changed,
            dbus_interface="org.freedesktop.DBus.Properties",
        )

        # 运行主循环
        loop = GLib.MainLoop()
        loop.run()

    except KeyboardInterrupt:
        print("\n退出监听")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MPRIS 歌曲元数据获取工具")
    parser.add_argument(
        "--monitor", action="store_true", help="启用监听模式，实时显示歌曲变化"
    )

    args = parser.parse_args()

    if args.monitor:
        demo_monitor()
    else:
        demo_basic()
