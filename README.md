# Purivox

<p align="left">
  <strong>简体中文</strong> · <a href="README_EN.md">English</a>
</p>

**[▶ 在浏览器中直接使用](https://purivox.wwchun.top/)**（基于 WebAssembly，纯本地计算，音频不会上传至服务器）

Purivox 是一款面向舞台与现场录音的伴奏/垫音消除（Vocal Isolation）工具，提供桌面端与浏览器端两种运行形态，基于 Python、PySide6 及 PySide6-Fluent-Widgets 构建。核心的参考消音功能遵循统一的处理流程：输入一段舞台/现场录音，并提供对应的歌曲参考音源。

- **单音源模式**：自动对齐并消除该歌曲成分。当音源与录音时长基本一致时，支持全时长全局倍速与时钟漂移校正；若仅覆盖录音局部，则在匹配区间内分段处理。
- **多音源模式**：自动在长录音中定位各歌曲所在时间范围，并对各匹配片段分别执行消除。输入音源文件的顺序不影响定位结果。

参考对消仅处理能被参考音源解释的重放音频成分，因此会保留音源中不存在的现场人声、讲话、观众互动与环境杂音。消除效果取决于参考音源的准确性；若录音存在严重削波、大混响、与音源编曲版本不一致或音源选择有误，处理质量会有所下降。

如需不依赖参考音源的两轨纯伴奏/人声分离，建议使用 [Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui) 等基于神经网络的深度学习工具；Purivox 专注于基于参考信号的相干对消。

## 主要特性

- **现代界面**：基于 Fluent Design 构建，支持浅色、深色及跟随系统主题。
- **多语言支持**：支持简体中文、繁体中文、英语、日语和韩语即时切换。
- **高精度 DSP**：集成全局倍速估计与保音高拉伸（WSOLA）、粗时延对齐、局部时钟漂移跟踪及复数相干传递估计。
- **智能时间线**：支持多音源识别、重复片段聚类与交互式时间线编辑。
- **高效内存管理**：长音频流式分块处理（`BLOCK_FRAMES`）、协作式任务取消及原子化写入保障。
- **真实规格输出**：导出音频严格沿用输入文件的采样率与对应位深，不进行无实际频谱增益的升采样。
- **结果审查**：内置轻量播放器支持即时试听与音频统计信息查看。
- **版本更新检查**：支持在设置页手动检查 GitHub Release 更新并查看更新日志。
- **崩溃诊断**：按日期轮转本地日志，未捕获异常提供结构化日志查看与一键提交 Issue 入口。
- **快捷键支持**：`Ctrl+O` 打开文件、`Ctrl+Return` 开始处理、`F5` 识别歌曲、`Esc` 取消、`Ctrl+P` 播放/暂停试听。
- **链接获取音源**：支持通过 YouTube / YouTube Music 链接解析并下载参考音源，具备本地去重缓存。
- **架构同构**：图形界面、命令行与 WebAssembly 浏览器端共享相同的核心算法管线。

## 安装指南

### 浏览器端

若无需本地安装，可直接访问 [WebAssembly 浏览器版](https://purivox.wwchun.top/)。浏览器端复用相同的计算管线，由于受浏览器标签页堆内存上限约束，更适合处理中短音频，详见[浏览器版（WebAssembly）说明](docs/web.md)。

### 桌面端安装包

可直接前往 [Release 发布页](https://github.com/ChouChiu/Purivox/releases/latest) 下载预编译安装包：
- **Windows**：`Purivox.exe`
- **Linux**：`.deb`、`.rpm` 或自解压包 `purivox-linux-x86_64.tar.gz`
- **macOS**：`purivox-macos-arm64.tar.gz`（Apple Silicon）或 `purivox-macos-x86_64.tar.gz`（Intel）

发布包均附带 `SHA256SUMS` 校验文件。macOS 版本首次打开时，若提示未签名，请在“访达”中右键点击 `Purivox.app` 并选择“打开”。

### 源码运行

从源码运行需使用 [uv](https://docs.astral.sh/uv/) 包管理器。项目通过 `.python-version` 锁定 Python 版本并在项目目录内维护隔离环境：

```bash
uv sync --locked
```

启动桌面图形界面：

```bash
uv run --locked purivox
```

## 图形界面使用

### 垫音消除

1. 进入“垫音消除”页面，选择待处理的舞台/现场录音文件。
2. 添加可能出现在录音中的歌曲参考音源。单份音源直接针对该曲消除，多份音源将在录音中自动定位。
3. 存在多份音源时，点击“识别歌曲”，查看识别出的完整歌曲、短片段、未匹配区间及置信度。
4. 检查时间线，可双击调整录音时间或音源范围，或取消勾选不需处理的片段。
5. 在“导出内容”中指定输出音轨：仅消音结果（现场人声）、仅垫音（Backing），或两者同时导出。垫音轨基于估计的传递函数从原始音源重新渲染生成，在保留音源原始品质的同时反映现场重放的频响与电平。
6. 调整消除强度后开始处理。若试听发现人声变薄或出现过度抑制的抽吸感，可调低强度或核对参考音源版本。

> **提示**：请尽量选用与现场重放一致的母带版本。编曲变动、升降调、重新剪辑均会导致对消效果下降。未匹配区间将保持现场原音复制，不会被自动截断。

### 从链接获取参考音源

在录音选择栏与音源列表中均提供「获取」按钮：

1. 支持直接粘贴 YouTube 或 YouTube Music 播放链接，或输入关键词搜索 YouTube 视频。
2. 下载任务会自动记录在「已下载」列表中，重复链接将直接复用缓存。
3. 链接附带播放列表参数时，仅提取当前单曲，不拉取整个播放列表。
4. 在列表中选择所需音频后点击「使用所选」，即自动填入对应输入框。

若系统安装有 FFmpeg，下载音频将转换为标准 WAV；未安装时保留原始容器文件，由解码回退流程读取。下载文件存放于应用数据目录的 `downloads/` 路径下。

## 命令行使用

### 查看帮助与版本

```bash
uv run --locked purivox --version
uv run --locked purivox --help
uv run --locked purivox mr --help
```

### 参考对消

执行标准参考对消：

```bash
uv run --locked purivox mr "现场录音.wav" "歌曲音源.wav" "现场人声.wav"
```

指定消除强度、分析窗口并开启自动对齐：

```bash
uv run --locked purivox mr "现场录音.wav" "歌曲音源.wav" "现场人声.wav" \
  --strength 75 --sigma 8 --align
```

常用参数说明：

| 参数 | 可选值 | 说明 |
|---|---:|---|
| `--strength` | `0`～`100` | 垫音消除强度，默认 `75` |
| `--sigma` | `1`、`3`、`8`、`16` | 统计窗口秒数，默认 `3`（GUI 固定使用 `3`） |
| `--align` / `--no-align` | 开 / 关 | 是否执行自动时延与漂移对齐，默认开启 |
| `--tracks` | `vocal`、`backing`、`both` | 导出内容，默认 `vocal`（仅消音结果） |
| `--lang` | `zh_cn`、`zh_tw`、`en_us`、`ja_jp`、`ko_kr` | 控制台进度信息语言 |

### 音源下载

```bash
uv run --locked purivox fetch "https://www.youtube.com/watch?v=..."   # 直接下载
uv run --locked purivox fetch "关键词" --limit 5                      # 搜索候选
uv run --locked purivox fetch "关键词" --pick 2                       # 下载指定序号项
uv run --locked purivox fetch --list                                  # 列出本地下载缓存
```

| 参数 | 可选值 | 说明 |
|---|---:|---|
| `--out` | 目录路径 | 保存目录，默认存放于应用数据目录下的 `downloads/` |
| `--limit` | 整数 | 搜索结果数量上限，默认 `10` |
| `--pick` | 整数 | 下载搜索列表中的指定条目（从 1 开始）；不指定则仅展示结果 |
| `--list` | 开关 | 列出已下载缓存列表 |

下载成功后将在标准输出打印生成的文件绝对路径，可直接与 `purivox mr` 配合使用。

## 输入输出规范与技术说明

- **格式支持**：WAV、FLAC、OGG 等常见无损及压缩格式由 libsndfile 原生支持；系统支持的其他媒体格式尝试通过 Qt Multimedia 接口解码。
- **采样率与规格**：参考对消全程在现场音频的原始采样率下处理，输出文件严格保持输入采样率与对应格式位深（8-bit / 16-bit PCM 输出 16-bit；24-bit / 32-bit PCM、浮点及有损格式输出 24-bit PCM），不进行虚假的升采样。
- **文件保护**：输出文件不可覆盖任一输入源文件。写出流程采用临时文件加原子替换（`os.replace`），避免任务中断损坏原文件或输出残留半成品。
- **任务取消**：支持通过 `Ctrl+C`（CLI）或界面按钮协作式中止任务。

## 技术文档

算法设计、数据流架构与开发指南参见 [docs/](docs/README.md)：

- [架构与数据流](docs/architecture.md)
- [参考对消](docs/reference-removal.md)
- [音源匹配、时间线与分段渲染](docs/matching.md)
- [浏览器版（WebAssembly）](docs/web.md)
- [开发与贡献](docs/CONTRIBUTING.md)

## 许可证与致谢

- [Vocal-Extractor](https://github.com/IamYei/Vocal-Extractor)：频域人声消除思路参考。
- [Ultimate Vocal Remover GUI](https://github.com/Anjok07/ultimatevocalremovergui)：无参考音源场景的深度学习分离基准工具。

本项目采用 [AGPL-3.0-or-later](LICENSE) 许可证开源发布。使用的 PySide6-Fluent-Widgets 遵循 GPLv3，商业使用请遵循上游许可条款。
