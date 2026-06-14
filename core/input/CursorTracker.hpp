#pragma once

enum class CompositorType { Hyprland, Sway, Generic };

namespace CursorTracker {

CompositorType detectCompositor();

bool getGlobalPosition(int &x, int &y);

} // namespace CursorTracker
