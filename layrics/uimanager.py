"""UI event dispatch: drains right-click menu events from the C++ core.

Events arrive as strings via ApplicationController.poll_ui_events();
menu_requested triggers a rebuild+push of the menu items (content lives on
Python side), any other event is a clicked action forwarded to ui_action().
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


class UIManager:
    """Polls UI (menu) events from the core and dispatches actions."""

    POLL_INTERVAL = 0.01

    def __init__(self, app):
        self._app = app
        self._ctrl = app.ctrl

    async def poller(self) -> None:
        """Drain menu events from the core and dispatch them.

        Runs as an asyncio task; cancel it to stop processing.
        """
        while True:
            try:
                for event in self._ctrl.poll_ui_events():
                    logger.debug("ui event: %s", event)
                    if event == "menu_requested":
                        await self._app.refresh_menu()
                    else:
                        await self._app.ui_action(event)
            except Exception:
                logger.exception("ui event polling failed")
            await asyncio.sleep(self.POLL_INTERVAL)
