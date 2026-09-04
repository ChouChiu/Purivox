# Purivox

<p align="left">
  <strong>简体中文</strong> · <a href="README_EN.md">English</a>
</p>

**[▶ 在浏览器中直接使用](https://purivox.wwchun.top/)**——无需安装，
音频全程留在你自己的标签页里，不会上传到服务器。

Purivox 是一款面向舞台和现场录音的垫音消除工具，有桌面版和浏览器版两种形态，
基于 Python、PySide6 和 PySide6-Fluent-Widgets 开发。核心的 MR Remove 功能支持两种处理方式：

- **单曲垫音消除**：提供舞台 / 现场音频和对应的歌曲音源，程序自动完成同步并去除垫音。
- **整场垫音消除**：提供整场舞台 / 现场音频和多个歌曲音源，
  程序自动定位每首歌出现的位置并分段去除垫音。

垫音消除只处理歌曲音源能够解释的内容，因此会保留音源中没有的现场人声、讲话、欢呼和环境声。
歌曲音源越准确，效果越好；录音削波、明显混响、编曲不同或选错音源，都会影响结果。

项目还附带一个独立的 **AI 音轨分离工具**，它用 UVR MDX-Net ONNX 模型把普通音频
分成预测人声与背景两条音轨。AI 分离不使用歌曲音源，也不执行 MR Remove 的匹配、对齐和垫音消除；
两者的目标和输出含义不同，AI 分离不能替代 MR Remove，其结果也不适合与 MR Remove 的垫音消除效果
直接比较。

## 主要功能

- Fluent Design 桌面界面，支持浅色、深色和跟随系统主题
- 中文、英文、日语和韩语界面即时切换
- 全局时间对齐、局部时钟漂移跟踪和基于参考的相干对消
- 整场录音歌曲识别、重复片段识别和可编辑的处理范围
- 附带 4 个可选 MDX-Net 分离模型，缺文件时自动下载并校验 SHA-256
- 长音频分块处理、任务取消和安全的原子写入
- 导出沿用输入文件的采样率与位深，不为凑规格而升采样
- 处理完成后可在应用内试听并查看音频统计信息
- 设置页可检查新版本，有更新时弹窗显示 Changelog 并跳转 Release 页面，不做自动更新
- 常用操作有快捷键：`Ctrl+O` 选择输入、`Ctrl+Return` 开始、
  `F5` 识别歌曲、`Esc` 取消、`Ctrl+P` 试听播放 / 暂停
- 图形界面与命令行共用对应的 MR Remove 与 AI 分离处理管线

## 安装

不想安装可以直接用[浏览器版](https://purivox.wwchun.top/)：
它跑的是同一套处理管线，只是不含 AI 音轨分离
（其依赖的 ONNX 运行时没有浏览器版本），且受浏览器内存上限约束，整场录音过长时会被拒绝。
详见[浏览器版（WebAssembly）](docs/web.md)。

桌面版可以直接从 [Release 页面](https://github.com/ChouChiu/Purivox/releases/latest)
下载：Windows 用 `Purivox.exe`，Linux 用 `.deb`、`.rpm` 或自解压的
`purivox-linux-x86_64.tar.gz`，macOS（Apple Silicon）用 `purivox-macos-arm64.tar.gz`，
每次发布都附带 `SHA256SUMS`。

macOS 版解压得到 `Purivox.app`，拖进“应用程序”即可；它只有 ad-hoc 签名，没有 Apple 开发者签名，
所以第一次打开要在访达里右键选“打开”。依赖里 ONNX Runtime 的 arm64 wheel 要求 macOS 14 或更高。

从源码运行需要先安装 [uv](https://docs.astral.sh/uv/)。
项目会根据 `.python-version` 自动选择 Python 版本，
并在仓库内维护隔离环境。请不要在该环境中安装其他会导出 `qfluentwidgets` 的 Qt Fluent 组件。

```bash
uv sync --locked
```

启动图形界面：

```bash
uv run --locked purivox
```

## 图形界面使用方法

### 单曲垫音消除

1. 打开“垫音消除”，选择“单曲”。
2. 选择要处理的舞台 / 现场音频，以及内容对应的歌曲音源。
3. 程序会自动对齐。建议先用默认的 75% 强度处理，图形界面使用固定的统计窗口。
4. 试听结果后再调整强度。如果声音出现明显的抽吸感，或人声变薄，
   请降低强度，或确认歌曲音源选择是否正确。

请尽量使用与现场一致的歌曲版本。母带不同、经过剪辑、变速、升降调或包含额外内容，都会降低消除效果。

### 整场垫音消除

1. 在“垫音消除”中选择“整场”，载入整场舞台 / 现场音频。
2. 添加可能在整场录音中出现的歌曲音源；文件顺序不影响识别。
3. 点击“识别歌曲”，检查完整歌曲、短片段、未识别区间和匹配度。
4. 必要时双击修改录音时间或音源范围，也可以取消勾选不想处理的片段。
5. 确认保存位置和处理选项后，开始处理整场录音。

未识别区间会按原样保留，时长不变，因此串场讲话、观众互动、广告和空场不会被自动剪掉。整场处理
目前只在图形界面中提供。

### 独立工具：AI 音轨分离

AI 音轨分离面向普通的两轨分离需求，不使用歌曲音源，也不是 MR Remove 的备用模式。

1. 打开“AI 音轨分离”，选择输入音频和模型。
2. 点击“开始分离”。
3. 首次使用某个模型时，程序会自动下载权重文件，请保持网络畅通并等待校验完成。

处理完成后会生成：

- `<歌曲名>_vocal.wav`：模型预测的人声
- `<歌曲名>_background.wav`：原始混音减去预测人声得到的背景

## 命令行使用方法

查看版本和帮助：

```bash
uv run --locked purivox --version
uv run --locked purivox --help
uv run --locked purivox mr --help
uv run --locked purivox ai --help
```

用默认参数执行参考对消：

```bash
uv run --locked purivox mr "现场录音.wav" "歌曲音源.wav" "现场人声.wav"
```

也可以在命令行中指定强度和统计窗口：

```bash
uv run --locked purivox mr "现场录音.wav" "歌曲音源.wav" "现场人声.wav" \
  --strength 75 --sigma 8 --align
```

常用参考对消参数：

| 参数 | 取值 | 说明 |
|---|---:|---|
| `--strength` | `0`～`100` | 垫音消除强度，默认 `75` |
| `--sigma` | `1`、`3`、`8`、`16` | 统计窗口秒数（进阶参数），默认 `3`；图形界面固定使用 `3` |
| `--align` / `--no-align` | 开 / 关 | 是否自动对齐，默认开启 |
| `--lang` | `zh_cn`、`en_us`、`ja_jp`、`ko_kr` | 进度信息语言 |

独立运行 AI 分离工具：

```bash
uv run --locked purivox ai "歌曲.wav" --output-dir "输出目录" --model mdxnet_1
```

可用模型为 `mdxnet_1`、`mdxnet_main`、`kim_vocal` 和 `kuielab_b`。可以用 `--models-dir`
指定权重目录，也可以用 `PURIVOX_MODELS` 环境变量设置共享的模型目录。

## 输入、输出与注意事项

- WAV、FLAC、OGG 等格式由 libsndfile 直接支持；系统可以解码的其他格式会尝试通过 Qt Multimedia 读取。
- MR Remove 与整场处理全程在舞台 / 现场音频的原始采样率下工作，导出同样保持该采样率。
- 独立 AI 分离工具仍按模型要求在 44.1 kHz 下推理，随后重采样回歌曲原采样率再导出双声道 WAV；
  其输出不等同于 MR Remove 结果。
- 导出的 PCM WAV 沿用输入文件的采样率与位深：8-bit 与 16-bit PCM 输入写出 16-bit，更宽的
  24/32-bit PCM、浮点以及所有有损格式写出 24-bit。升采样不会凭空产生输入或模型里没有的频谱细节，
  只会让文件变大，因此不做这一步。
- 输出路径不能覆盖任何输入文件。按 `Ctrl+C` 可取消命令行任务。
- 模型权重不会包含在 Python 包或独立程序中。
- 合成测试只能说明实现没有明显退化，最终效果请以同一素材处理前后的试听对比为准。

## 技术文档

算法、架构、测试和发布说明已移至 [docs/](docs/README.md)：

- [架构与数据流](docs/architecture.md)
- [参考对消](docs/reference-removal.md)
- [完整舞台实现](docs/full-stage.md)
- [AI 音轨分离实现](docs/neural-separation.md)
- [浏览器版（WebAssembly）](docs/web.md)
- [开发、测试与发布](docs/development.md)

## 致谢与许可

- [Vocal-Extractor](https://github.com/IamYei/Vocal-Extractor)：为频域人声提取方向提供启发。
- [Ultimate Vocal Remover GUI](https://github.com/Anjok07/ultimatevocalremovergui)：
  AI 处理流程参考其 MDX-Net 管线。
- [TRvlvr/model_repo](https://github.com/TRvlvr/model_repo)：
  提供 MDX-Net 模型文件；模型许可与致谢要求以各发布页为准。

本项目以 [AGPL-3.0-or-later](LICENSE) 发布。PySide6-Fluent-Widgets
开源版本使用 GPLv3，商业使用前请先确认其上游许可。
