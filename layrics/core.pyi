class StateView:
    paused: bool
    hidden: bool
    locked: bool
    start_time_ms: int
    drag_offset_x: float
    drag_offset_y: float
    target_fps: int

class ApplicationController:
    def __init__(self) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def join(self) -> None: ...
    def set_ass_input(self, content: str) -> None: ...
    def set_status(
        self,
        *,
        paused: bool = ...,
        hidden: bool = ...,
        locked: bool = ...,
        start_time_ms: int = ...,
        target_fps: int = ...,
    ) -> None: ...
    @property
    def state(self) -> StateView: ...
