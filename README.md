> [!NOTE]
> **免责声明／Disclaimer**
>
> 本项目的开发过程大量使用了 AI 辅助编程工具。代码可能存在未预料的行为或缺陷，请自行评估风险后使用。
>
> This project was developed with extensive use of AI-assisted coding tools. The code may contain unexpected behavior or bugs. Use at your own risk.

---

# layrics

layrics 是一款运行在 wlr-layer-shell 上的 ASS 字幕叠加层。可以在支持 `wlr-layer-shell` 协议的 Wayland 合成器（Sway、Hyprland、river 等）上，以overlay的形式渲染karaoke 或纯文本歌词字幕。

## 功能

- **Layer Shell 覆盖层**：全屏覆盖层，纯 CPU 渲染，无需 GPU/EGL
- **libass 渲染**：支持 ASS 字幕全部特性，包括卡拉 OK（`\kf`）、样式、字体和特效
- **多源歌词搜索**：跨 QQ 音乐、网易云音乐、LRCLIB 搜索，自动匹配歌曲
- **MPRIS 集成**：自动发现并同步 MPRIS 兼容播放器（Spotify、mpv 等）
- **拖拽支持**：点击拖拽覆盖层重新定位字幕位置
- **IPC 控制**：Unix domain socket JSON 协议，支持程序化控制
- **可配置输出**：TOML 配置字体、颜色、定位、渲染模式
- **Python/C++ 混合架构**：性能关键渲染层用 C++ + libass，编排逻辑用 Python

## 架构

```
layrics (Python)                    
├── main.py          IPC 服务端     
│   ├── MPRIS 同步  MPRIS 轮询      
│   ├── 歌词获取    LDDC 适配器     
│   └── IPC 服务端  Unix socket     
├── lyricsource.py  搜索/获取       
├── matching.py     歌曲匹配        
├── layctl.py       控制 CLI        
├── mpris.py        D-Bus 信号      
├── assprovider/    ASS 生成        
└── config.py       TOML 配置       
                                    
                                    
C++ overlay (core/)                            
├── Application      事件循环、帧调度          
├── ApplicationController  线程安全命令队列    
├── RenderManager    cairo 合成 + 拖拽偏移     
├── AssRenderer      libass -> cairo surface   
├── LayerSurface     wlr-layer-shell surface   
├── ShmBuffer        SHM pool -> wl_buffer     
├── InputManager     wl_pointer 事件           
├── DragManager      拖拽状态机                
├── RegionManager    input region              
├── CursorTracker    全局光标（Hyprland）      
├── WaylandContext   display、全局对象、事件循 
└── binding.cpp      pybind11 绑定              

```

## 安装

### 系统依赖

- `wayland-client`、`wayland-scanner`
- `cairo`
- `libass`
- `meson`（>= 1.3.0）
- `pkg-config`

### Python 依赖（pip 自动安装）

- `meson-python`、`pybind11`（构建时）
- `httpx`、`dbus-python`、`PyGObject`、`click`、`appdirs`（运行时）

### 安装

```bash
git clone --recursive https://github.com/yourname/layrics
cd layrics
pip install .
```

`--recursive` 参数用于拉取歌词源所需的 vendored `LDDC` git 子模块。

### 开发安装

```bash
pip install -e .
```

## 使用

### 启动叠加层守护进程

```bash
layrics
```

守护进程会：
1. 连接 Wayland 并创建覆盖层 surface
2. 自动选择 MPRIS 兼容播放器
3. 轮询曲目变化并自动获取歌词

可选参数：
- `--socket, -s PATH`  — 自定义 IPC socket 路径（默认：`$XDG_RUNTIME_DIR/layrics.sock`）
- `ass_file`           — 启动时加载 ASS 文件(用于debug)

### 使用 layctl 控制

```bash
# 列出可用 MPRIS 播放器
layctl list-players

# 选择播放器
layctl select-player spotify

# 搜索歌曲
layctl search "Eternal Feather"

# 获取指定歌曲歌词并显示在覆盖层
layctl fetch QM248672467 --sync

# 获取当前曲目歌词
layctl fetch --sync

# 显示/隐藏覆盖层
layctl show
layctl hide

# 查看当前状态
layctl status
```

### IPC 协议

守护进程监听 Unix domain socket。请求和响应均为 JSON 行格式：

```
{"id": 1, "method": "list_players"}
{"id": 1, "type": "result", "data": [{"bus_name": "...", "identity": "..."}]}
```

可用方法：`list_players`、`select_player`、`search_songs`、`fetch_lyrics`、`load_ass`、`hide`、`unhide`、`stop`、`start`、`get_status`。

## 配置

配置文件路径：`~/.config/layrics/config.toml`（或 `$LAYRICS_CONFIG_DIR/config.toml`）。

```toml
# 播放器自动选择过滤规则（正则，匹配 bus_name 和 identity）
include_players = ["spotify", "mpv"]

# 字体映射（按语言）
[fonts]
ja = "Noto Sans CJK JP"
zh = "Noto Sans CJK SC"
ko = "Noto Sans CJK KR"
default = "Noto Sans"

# 样式覆写
[style.primary]
font_size = 48
primary_colour = "&H00E6D8AD"
secondary_colour = "&H00AAAAAA"
outline = 2.0
shadow = 2.0

[style.secondary]
font_size = 32
primary_colour = "&H00CCCCCC"

# 提供者配置
[assprovider.default]
karaoke = true
line_mode = "single"
advance_ms = 1500
double_margin_max_length = 960
```

## ASS 提供者系统

`assprovider` 包负责将 LRC 歌词转换为 ASS 字幕格式。

### 渲染模式

- **卡拉 OK**（`karaoke=true`）：生成 `\kf` 标签实现逐音节填色。`PrimaryColour` 为填充色，`SecondaryColour` 为等待色。
- **单行模式**（`line_mode="single"`）：一次显示一行，居中，可选择显示翻译/罗马音（第二语言）。
- **双行模式**（`line_mode="double"`）：两行同时显示（左右交替）。启用 `advance_ms` 时，歌词在预显示窗口期内显示为暗淡色，到播放时间后切换为高亮色。

### 语言检测

提供者通过字符集分析自动检测歌词语言（假名 -> 日语、谚文 -> 韩语、西里尔 -> 俄语、CJK -> 中文），并从配置中选择对应字体。

### 歌曲匹配

获取当前曲目歌词时，系统：
1. 在所有可用源中搜索歌曲
2. 按标题相似度、时长差异、歌手相似度打分
3. 使用级联评分系统选择最佳匹配

## 仅编译 C++ 部分

```bash
meson setup build
meson compile -C build
./build/examples/layrics test.ass
```

---

## 参考致谢

- [Waifuland](https://github.com/shinkuan/Waifuland) — 拖拽实现与全局光标获取的参考
- [wob](https://github.com/francma/wob) — wlr-layer-shell C 实现，架构与结构体设计参考
- [waynav](https://github.com/kovetskiy/waynav) — 输入区域管理的参考
- [LDDC](https://github.com/chenmozhijin/LDDC) — 多源歌词搜索与获取库
- [waylyrics](https://github.com/waylyrics/waylyrics) — 功能设计与整体思路的灵感来源

---

# layrics (English)

---

ASS subtitle overlay for wlr-layer-shell. Renders karaoke and plain-text subtitles as an overlay on Wayland compositors that support `wlr-layer-shell` (Sway, Hyprland, river, etc.).

---

## Features

- **Layer Shell overlay**: fullscreen overlay layer rendered entirely on CPU (no GPU/EGL required)
- **libass rendering**: supports ASS subtitle features including karaoke (`\kf`), styling, fonts, and effects
- **Multi-source lyric fetching**: searches across QQ Music, NetEase, and LRCLIB with automatic song matching
- **MPRIS integration**: auto-detects and syncs with MPRIS-compatible players (Spotify, mpv, etc.)
- **Drag support**: click and drag the overlay to reposition subtitles
- **IPC control**: Unix domain socket JSON protocol for programmatic control
- **Configurable output**: TOML configuration for fonts, colors, positioning, and render modes
- **Python/C++ hybrid**: performance-critical rendering in C++ with libass, orchestration in Python

## Architecture

```
layrics (Python)                    C++ overlay (core/)
├── main.py          IPC server     ├── Application      event loop, frame scheduling
│   ├── MPRIS sync  MPRIS polling  ├── ApplicationController  thread-safe command queue
│   ├── lyric fetch LDDC adapter   ├── RenderManager     cairo composition + drag offset
│   └── IPC server  Unix socket    ├── AssRenderer       libass -> cairo surface
├── lyricsource.py  search/fetch   ├── LayerSurface      wlr-layer-shell surface
├── matching.py     song matching  ├── ShmBuffer         SHM pool -> wl_buffer
├── layctl.py       control CLI    ├── InputManager      wl_pointer events
├── mpris.py        D-Bus signals  ├── DragManager       drag state machine
├── assprovider/    ASS generation ├── RegionManager     input region
└── config.py       TOML config     ├── CursorTracker    global cursor (Hyprland)
                                    ├── WaylandContext   display, globals, event loop
                                    └── binding.cpp      pybind11 bindings
```

## Installation

### System dependencies

- `wayland-client`, `wayland-scanner`
- `cairo`
- `libass`
- `meson` (>= 1.3.0)
- `pkg-config`

### Python dependencies (installed automatically via pip)

- `meson-python`, `pybind11` (build)
- `httpx`, `dbus-python`, `PyGObject`, `click`, `appdirs` (runtime)

### Install

```bash
git clone --recursive https://github.com/yourname/layrics
cd layrics
pip install .
```

The `--recursive` flag is required to fetch the vendored `LDDC` git submodule for lyric sources.

### Development install

```bash
pip install -e .
```

## Usage

### Start the overlay daemon

```bash
layrics
```

The daemon:
1. Connects to Wayland and creates an overlay surface
2. Auto-selects an MPRIS-compatible player
3. Polls for track changes and fetches lyrics automatically

Optional arguments:
- `--socket, -s PATH`  — custom IPC socket path (default: `$XDG_RUNTIME_DIR/layrics.sock`)
- `ass_file`           — load an ASS file on startup

### Control with layctl

```bash
# List available MPRIS players
layctl list-players

# Select a specific player
layctl select-player spotify

# Search for songs
layctl search "Eternal Feather"

# Fetch lyrics for a specific song and display on overlay
layctl fetch QM248672467 --sync

# Fetch lyrics for the current track
layctl fetch --sync

# Show/hide overlay
layctl show
layctl hide

# Get current status
layctl status
```

### IPC Protocol

The daemon listens on a Unix domain socket. Requests and responses are JSON lines:

```
{"id": 1, "method": "list_players"}
{"id": 1, "type": "result", "data": [{"bus_name": "...", "identity": "..."}]}
```

Available methods: `list_players`, `select_player`, `search_songs`, `fetch_lyrics`, `load_ass`, `hide`, `unhide`, `stop`, `start`, `get_status`.

## Configuration

Configuration is loaded from `~/.config/layrics/config.toml` (or `$LAYRICS_CONFIG_DIR/config.toml`).

```toml
# Player auto-selection filters (regex matched against bus_name and identity)
include_players = ["spotify", "mpv"]

# Font mapping by language
[fonts]
ja = "Noto Sans CJK JP"
zh = "Noto Sans CJK SC"
ko = "Noto Sans CJK KR"
default = "Noto Sans"

# Style overrides
[style.primary]
font_size = 48
primary_colour = "&H00E6D8AD"
secondary_colour = "&H00AAAAAA"
outline = 2.0
shadow = 2.0

[style.secondary]
font_size = 32
primary_colour = "&H00CCCCCC"

# Provider configuration
[assprovider.default]
karaoke = true
line_mode = "single"
advance_ms = 1500
double_margin_max_length = 960
```

## ASS Provider System

The `assprovider` package handles converting LRC lyrics to ASS subtitle format.

### Modes

- **Karaoke** (`karaoke=true`): generates `\kf` tags for syllable-by-syllable color fill. `PrimaryColour` is the fill/overlay colour, `SecondaryColour` is the dim/waiting colour.
- **Single line** (`line_mode="single"`): one line at a time, centered, with optional secondary language (translation/romaji) below.
- **Double line** (`line_mode="double"`): two lines displayed simultaneously (left/right alternating). With `advance_ms`, lines appear dimmed during the pre-display window and switch to full brightness when their play time begins.

### Language detection

The provider auto-detects lyrics language by character set analysis (kana -> Japanese, hangul -> Korean, Cyrillic -> Russian, CJK -> Chinese) and selects the appropriate font from the configuration.

### Song matching

When fetching lyrics for the current track, the system:
1. Searches for the song across all available sources
2. Scores candidates by title similarity, duration difference, and artist similarity
3. Selects the best match using a cascade scoring system

## Building from source (C++ only)

```bash
meson setup build
meson compile -C build
./build/examples/layrics test.ass
```

## License

MIT

---

## Credits

- [Waifuland](https://github.com/shinkuan/Waifuland) — reference for drag implementation and global cursor tracking
- [wob](https://github.com/francma/wob) — wlr-layer-shell C implementation, architecture and struct design reference
- [waynav](https://github.com/kovetskiy/waynav) — reference for input region management
- [LDDC](https://github.com/chenmozhijin/LDDC) — multi-source lyric search and fetching library
- [waylyrics](https://github.com/waylyrics/waylyrics) — inspiration for feature design and overall approach
