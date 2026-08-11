project(
  'layrics-core',
  ['c', 'cpp'],
  meson_version : '>= 1.3.0',
  version : '0.1.0',
  default_options : ['warning_level=3', 'cpp_std=c++20', 'buildtype=debugoptimized'],
)

wayland_scanner = find_program('wayland-scanner')
wayland_client_dep = dependency('wayland-client')
wayland_cursor_dep = dependency('wayland-cursor')
libass_dep = dependency('libass')
vulkan_dep = dependency('vulkan')
glslc = find_program('glslc')

layer_shell_xml = files('protocol/wlr-layer-shell-unstable-v1.xml')
xdg_shell_xml = files('protocol/xdg-shell.xml')

layer_shell_header = custom_target(
  'wlr-layer-shell-unstable-v1-header',
  command: [wayland_scanner, 'client-header', '@INPUT@', '@OUTPUT@'],
  input: layer_shell_xml,
  output: 'wlr-layer-shell-unstable-v1.h',
)

fix_header = find_program('scripts/fix_wayland_header.py')

layer_shell_header_cpp = custom_target(
  'wlr-layer-shell-unstable-v1-cpp-header',
  command: [fix_header, '@INPUT@', '@OUTPUT@'],
  input: layer_shell_header,
  output: 'wlr-layer-shell-unstable-v1-cpp.h',
  build_by_default: true,
)

layer_shell_src = custom_target(
  'wlr-layer-shell-unstable-v1-source',
  command: [wayland_scanner, 'private-code', '@INPUT@', '@OUTPUT@'],
  input: layer_shell_xml,
  output: 'wlr-layer-shell-unstable-v1.c',
)

xdg_shell_header = custom_target(
  'xdg-shell-header',
  command: [wayland_scanner, 'client-header', '@INPUT@', '@OUTPUT@'],
  input: xdg_shell_xml,
  output: 'xdg-shell.h',
)

xdg_shell_src = custom_target(
  'xdg-shell-source',
  command: [wayland_scanner, 'private-code', '@INPUT@', '@OUTPUT@'],
  input: xdg_shell_xml,
  output: 'xdg-shell.c',
)

dependencies = [
  wayland_client_dep,
  wayland_cursor_dep,
  libass_dep,
  vulkan_dep,
  meson.get_compiler('cpp').find_library('rt', required: false),
  meson.get_compiler('cpp').find_library('m', required: false),
]

# Embed SPIR-V shaders as C arrays: glslc -mfmt=c emits a bare initializer
# list; the array declaration lives at the include site (VulkanContext.cpp).
subtitle_vert_h = custom_target(
  'subtitle-vert-header',
  command: [glslc, '-mfmt=c', '-o', '@OUTPUT@',
            files('core/renderer/shaders/subtitle.vert')],
  output: 'subtitle_vert.inc',
  build_by_default: true,
)

subtitle_frag_h = custom_target(
  'subtitle-frag-header',
  command: [glslc, '-mfmt=c', '-o', '@OUTPUT@',
            files('core/renderer/shaders/subtitle.frag')],
  output: 'subtitle_frag.inc',
  build_by_default: true,
)

protocol_sources = [
  layer_shell_src,
  layer_shell_header_cpp,
  xdg_shell_src,
  xdg_shell_header,
]

wayland_sources = files(
  'core/wayland/WaylandContext.cpp',
  'core/wayland/LayerSurface.cpp',
)

input_sources = files(
  'core/input/InputManager.cpp',
  'core/input/DragManager.cpp',
  'core/input/CursorTracker.cpp',
  'core/input/CursorManager.cpp',
  'core/input/RegionManager.cpp',
  'core/input/DamageGrid.cpp',
  'core/input/KeyboardManager.cpp',
)

renderer_sources = files(
  'core/renderer/AssRenderer.cpp',
  'core/renderer/RenderManager.cpp',
  'core/renderer/VulkanContext.cpp',
)

utils_sources = files(
  'core/utils/FrameRateLimiter.cpp',
)

app_sources = files(
  'core/app/Application.cpp',
  'core/app/ApplicationController.cpp',
)

inc = include_directories('.')

# Python bindings via pybind11
pybind11_dep = dependency('pybind11', required: false)
if pybind11_dep.found()
  py = import('python').find_installation('python3', pure: false)
  py_dep = py.dependency()

  binding_sources = files(
    'core/binding.cpp',
  )

  all_core_sources = [
    wayland_sources,
    input_sources,
    renderer_sources,
    app_sources,
    utils_sources,
    protocol_sources,
    subtitle_vert_h,
    subtitle_frag_h,
  ]

  py.extension_module(
    'core',
    [binding_sources, all_core_sources],
    include_directories : inc,
    dependencies : [py_dep, pybind11_dep, dependencies],
    # Vulkan structs use designated initializers that omit zero-filled fields.
    cpp_args : ['-Wno-missing-field-initializers'],
    install : true,
    subdir : 'layrics',
  )

  install_subdir(
    'layrics',
    install_dir : py.get_install_dir(),
    strip_directory : false,
    exclude_directories : ['__pycache__'],
    exclude_files : ['*.pyc'],
  )


endif

# Headless unit test: renders an ASS frame offscreen (no Wayland surface, no
# presentation) and compares the GPU pixels against a CPU libass composite.
test_render_sources = files(
  'tests/ass_render_test.cpp',
  'core/renderer/AssRenderer.cpp',
  'core/renderer/RenderManager.cpp',
  'core/renderer/VulkanContext.cpp',
)

test_render_exe = executable('ass-render-test',
  [test_render_sources, subtitle_vert_h, subtitle_frag_h],
  include_directories : inc,
  dependencies : dependencies,
  # Vulkan structs use designated initializers that omit zero-filled fields.
  cpp_args : ['-Wno-missing-field-initializers'],
)

test('ass-render', test_render_exe)

