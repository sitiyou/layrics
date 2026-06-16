executable(
  'layrics',
  ['main.cpp', app_sources, wayland_sources, input_sources, renderer_sources, utils_sources, protocol_sources],
  include_directories : inc,
  dependencies : dependencies,
  install : true,
)

test_cursor_exe = executable(
  'test-cursor',
  ['test_cursor.cpp', input_sources],
  include_directories : inc,
  dependencies : dependencies,
  install : false,
)

test_simple_exe = executable(
  'test-simple',
  ['test_simple.cpp', wayland_sources, protocol_sources],
  include_directories : inc,
  dependencies : dependencies,
  install : false,
)

test_drag_exe = executable(
  'test-drag',
  ['test_drag.cpp', wayland_sources, input_sources, protocol_sources],
  include_directories : inc,
  dependencies : dependencies,
  install : false,
)
