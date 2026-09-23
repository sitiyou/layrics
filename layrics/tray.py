"""System tray icon (StatusNotifierItem over D-Bus).

Publishes ``org.kde.StatusNotifierItem`` on the session bus so panels (waybar,
KDE Plasma, ...) can show a tray icon: left click toggles the overlay, right
click asks the core to open its imgui menu at the pointer, so the tray menu
shares the look of the in-overlay right-click menu.

The item deliberately does not advertise a ``Menu`` property
(``com.canonical.dbusmenu``): hosts then fall back to the ``ContextMenu()``
method, which is what lets the menu be drawn by our own renderer.

D-Bus callbacks run on a GLib thread; they hop to the asyncio loop through
``run_coroutine_threadsafe``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

logger = logging.getLogger(__name__)

BUS_NAME = "org.layrics.Layrics"
ITEM_PATH = "/StatusNotifierItem"
ITEM_IFACE = "org.kde.StatusNotifierItem"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
WATCHER_SERVICE = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
WATCHER_IFACE = "org.kde.StatusNotifierWatcher"

DEFAULT_ICON = Path(__file__).resolve().parent / "data" / "icon.png"


def _load_icon_pixmap(path: Path) -> list[tuple[int, int, bytes]]:
    """Decode `path` into SNI IconPixmap data: [(width, height, ARGB32)]."""
    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
    except (ImportError, ValueError) as e:
        logger.warning("tray: GdkPixbuf unavailable, falling back to IconName: %s", e)
        return []
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
    except Exception as e:
        logger.warning("tray: cannot load icon %s: %s", path, e)
        return []
    if not pixbuf.get_has_alpha():
        pixbuf = pixbuf.add_alpha(False, 0, 0, 0)
    width = pixbuf.get_width()
    height = pixbuf.get_height()
    rowstride = pixbuf.get_rowstride()
    raw = pixbuf.get_pixels()
    if rowstride != width * 4:
        raw = b"".join(
            raw[y * rowstride : y * rowstride + width * 4] for y in range(height)
        )
    # GdkPixbuf hands out RGBA; SNI wants ARGB32 in network byte order.
    argb = bytearray(width * height * 4)
    argb[0::4] = raw[3::4]
    argb[1::4] = raw[0::4]
    argb[2::4] = raw[1::4]
    argb[3::4] = raw[2::4]
    return [(width, height, bytes(argb))]


class _StatusNotifierItem(dbus.service.Object):
    """The exported D-Bus object; one instance per running app."""

    _PROPERTIES = (
        "Category",
        "Id",
        "Title",
        "Status",
        "WindowId",
        "IconThemePath",
        "IconName",
        "IconPixmap",
        "OverlayIconName",
        "OverlayIconPixmap",
        "AttentionIconName",
        "AttentionIconPixmap",
        "AttentionMovieName",
        "ToolTip",
        "ItemIsMenu",
    )

    def __init__(self, bus, app, pixmap: list[tuple[int, int, bytes]]):
        self._app = app
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pixmap = dbus.Array(
            [
                dbus.Struct(
                    (dbus.Int32(w), dbus.Int32(h), dbus.ByteArray(data)),
                    signature="iiay",
                )
                for w, h, data in pixmap
            ],
            signature="(iiay)",
        )
        # Hosts prefer IconName over the pixmap, so only set it as a fallback.
        self._icon_name = "" if pixmap else "layrics"
        super().__init__(dbus.service.BusName(BUS_NAME, bus), ITEM_PATH)

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _dispatch(self, func, *args) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(func(*args), loop)

    # ── SNI methods ───────────────────────────────────────────────

    @dbus.service.method(ITEM_IFACE, in_signature="ii", out_signature="")
    def Activate(self, x, y):
        self._dispatch(self._app.toggle_visibility)

    @dbus.service.method(ITEM_IFACE, in_signature="ii", out_signature="")
    def ContextMenu(self, x, y):
        self._dispatch(self._app.open_menu_at, int(x), int(y))

    @dbus.service.method(ITEM_IFACE, in_signature="ii", out_signature="")
    def SecondaryActivate(self, x, y):
        pass

    @dbus.service.method(ITEM_IFACE, in_signature="is", out_signature="")
    def Scroll(self, delta, orientation):
        pass

    # ── org.freedesktop.DBus.Properties ───────────────────────────

    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        return self._property(prop)

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != ITEM_IFACE:
            return {}
        return {name: self._property(name) for name in self._PROPERTIES}

    @dbus.service.method(PROPS_IFACE, in_signature="ssv", out_signature="")
    def Set(self, interface, prop, value):
        raise dbus.exceptions.DBusException(
            "org.freedesktop.DBus.Error.PropertyReadOnly",
            "layrics status notifier properties are read-only",
        )

    def _property(self, name):
        if name == "Category":
            return dbus.String("ApplicationStatus")
        if name in ("Id", "Title"):
            return dbus.String("layrics")
        if name == "Status":
            return dbus.String("Active")
        if name == "WindowId":
            return dbus.UInt32(0)
        if name == "IconName":
            return dbus.String(self._icon_name)
        if name == "IconPixmap":
            return self._pixmap
        if name == "ToolTip":
            return dbus.Struct(
                (
                    dbus.String(""),
                    dbus.Array([], signature="(iiay)"),
                    dbus.String("layrics"),
                    dbus.String(""),
                ),
                signature="sa(iiay)ss",
            )
        if name == "ItemIsMenu":
            return dbus.Boolean(False)
        if name in (
            "IconThemePath",
            "OverlayIconName",
            "AttentionIconName",
            "AttentionMovieName",
        ):
            return dbus.String("")
        return dbus.Array([], signature="(iiay)")


class TrayIcon:
    """Owns the StatusNotifierItem and its GLib D-Bus thread."""

    def __init__(self, app, icon_path: str = ""):
        self._app = app
        self._icon_path = Path(icon_path) if icon_path else DEFAULT_ICON
        self._item: _StatusNotifierItem | None = None
        self._glib_loop: GLib.MainLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, args=(loop,), name="layrics-tray", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        glib_loop = self._glib_loop
        self._glib_loop = None
        self._thread = None
        if glib_loop is not None:
            glib_loop.quit()

    def _run(self, loop: asyncio.AbstractEventLoop) -> None:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        try:
            item = _StatusNotifierItem(
                bus, self._app, _load_icon_pixmap(self._icon_path)
            )
        except dbus.DBusException as e:
            logger.warning("tray: cannot export status notifier item: %s", e)
            return
        item.bind_loop(loop)
        self._item = item
        self._glib_loop = GLib.MainLoop()
        self._register(bus)
        self._watch_watcher(bus)
        self._glib_loop.run()

    @staticmethod
    def _register(bus) -> None:
        try:
            watcher = bus.get_object(WATCHER_SERVICE, WATCHER_PATH)
            watcher.RegisterStatusNotifierItem(BUS_NAME, dbus_interface=WATCHER_IFACE)
            logger.info("tray: registered with %s", WATCHER_SERVICE)
        except dbus.DBusException as e:
            logger.info("tray: %s unavailable: %s", WATCHER_SERVICE, e)

    def _watch_watcher(self, bus) -> None:
        # Panels can start after us (or restart); re-register when the watcher
        # reappears.
        bus.add_signal_receiver(
            self._on_name_owner_changed,
            signal_name="NameOwnerChanged",
            dbus_interface="org.freedesktop.DBus",
            arg0=WATCHER_SERVICE,
        )

    def _on_name_owner_changed(self, name, old_owner, new_owner) -> None:
        if new_owner:
            self._register(dbus.SessionBus())
