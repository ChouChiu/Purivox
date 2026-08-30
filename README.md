# Purivox

<p align="left">
  <strong>简体中文</strong> · <a href="README_EN.md">English</a>
</p>

Purivox 是一款面向舞台和现场录音的桌面垫音消除工具，使用 Python、PySide6 和
PySide6-Fluent-Widgets 构建。核心 MR Remove 功能提供两种处理方式：

- **单曲垫音消除**：输入舞台 / 现场音频和对应歌曲音源，自动同步并消除垫音。
- **整场垫音消除**：输入整场舞台 / 现场音频和多个歌曲音源，自动识别每首歌的位置并分段消除垫音。

垫音消除只处理能够由歌曲音源解释的内容，因此适合保留音源中不存在的现场人声、讲话、欢呼和环境声。
它依赖准确的歌曲音源；录音削波、严重混响、不同编曲或错误音源都会影响结果。

项目另附一个独立的 **AI 音轨分离工具**，使用 UVR MDX-Net ONNX 模型把普通音频预测为人声与背景音轨。
AI 分离不使用歌曲音源，也不执行 MR Remove 的匹配、对齐和垫音消除；两者目标及输出含义不同，AI 分离不能替代
MR Remove，其结果也不应与 MR Remove 的垫音消除效果直接比较。

## 主要功能

- Fluent Design 桌面界面，支持浅色、深色和跟随系统主题
- 中文、英文、日语和韩语界面即时切换
- 全局时间对齐、局部时钟漂移跟踪和参考相干对消
- 可选的“突出人声”和“开麦聚焦”处理
- 整场录音歌曲识别、重复片段识别和可编辑处理范围
- 独立附带 4 个可选 MDX-Net 分离模型，缺失时自动下载并校验 SHA-256
- 长音频分块处理、任务取消和原子写出
- 所有结果导出为至少 96 kHz、24-bit PCM WAV
- 处理完成后可在应用内试听并查看音频统计信息
- 音频文件可直接拖入界面；常用操作有快捷键：`Ctrl+O` 选择输入、`Ctrl+Return` 开始、`F5` 识别歌曲、`Esc` 取消、`Ctrl+P` 试听播放 / 暂停
- GUI 与命令行分别复用对应的 MR Remove 与 AI 分离任务管线

## 安装

需要 [uv](https://docs.astral.sh/uv/)；项目会按 `.python-version` 自动选择 Python，
并在仓库内管理隔离环境。不要向该环境混装其他导出 `qfluentwidgets` 的 Qt Fluent 组件。

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
2. 选择待处理的舞台 / 现场音频，以及与其内容对应的歌曲音源。
3. 程序会自动执行对齐；先使用默认的 75% 强度处理，图形界面会采用固定的统计上下文。
4. 试听结果后再调整强度。声音出现明显抽吸或人声变薄时，应降低强度或确认歌曲音源是否正确。
5. “突出人声”和“开麦聚焦”是可选处理；后者只能在前者开启时使用。

歌曲音源应尽量与现场使用的版本一致。不同母带、剪辑、变速、升降调或额外内容都会降低消除效果。

### 整场垫音消除

1. 在“垫音消除”中选择“整场”，载入整场舞台 / 现场音频。
2. 添加可能在整场录音中出现的歌曲音源；文件顺序不影响识别。
3. 点击“识别歌曲”，检查完整歌曲、短片段、未识别区间和匹配度。
4. 必要时双击修改录音时间或音源范围，也可取消勾选不想处理的片段。
5. 确认保存位置和处理选项后，开始处理整场录音。

未识别区间会保留原始内容和长度，因此串场讲话、观众互动、广告及空场不会被自动裁除。整场处理目前仅在图形界面中提供。

### 独立工具：AI 音轨分离

AI 音轨分离面向普通的两轨分离需求，不使用歌曲音源，也不是 MR Remove 的备用模式。

1. 打开“AI 音轨分离”，选择输入音频和模型。
2. 点击“开始分离”。
3. 首次使用某个模型时，程序会自动下载权重；请保持网络连接并等待校验完成。

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

使用默认参数进行参考对消：

```bash
uv run --locked purivox mr "现场录音.wav" "歌曲音源.wav" "现场人声.wav"
```

命令行可进一步指定强度、统计窗口并开启中置处理：

```bash
uv run --locked purivox mr "现场录音.wav" "歌曲音源.wav" "现场人声.wav" \
  --strength 75 --sigma 8 --align \
  --center-extraction --open-mic-focus
```

常用参考对消参数：

| 参数 | 取值 | 说明 |
|---|---:|---|
| `--strength` | `0`～`100` | 垫音消除强度，默认 `75` |
| `--sigma` | `1`、`3`、`8`、`16` | 高级统计窗口秒数，默认 `3`；图形界面固定使用 `3` |
| `--align` / `--no-align` | 开 / 关 | 是否自动对齐，默认开启 |
| `--center-extraction` | 开关 | 进一步突出位于左右声道中央的人声 |
| `--open-mic-focus` | 开关 | 开麦处保留更多中置人声、未开麦或只有垫音处继续压低，依赖中置处理 |
| `--lang` | `zh_cn`、`en_us`、`ja_jp`、`ko_kr` | 进度信息语言 |

独立运行 AI 分离工具：

```bash
uv run --locked purivox ai "歌曲.wav" --output-dir "输出目录" --model mdxnet_1
```

可用模型为 `mdxnet_1`、`mdxnet_main`、`kim_vocal` 和 `kuielab_b`。可用
`--models-dir` 指定权重目录，也可通过 `PURIVOX_MODELS` 环境变量设置公共模型目录。

## 输入、输出与注意事项

- libsndfile 原生支持 WAV、FLAC、OGG 等格式；其他系统可解码格式会尝试通过 Qt Multimedia 读取。
- MR Remove 与整场处理在舞台 / 现场音频的原始采样率下工作；低于 96 kHz 的结果在导出前使用 soxr 高质量重采样，高于 96 kHz 时保留原采样率。
- 独立 AI 分离工具仍按模型要求在 44.1 kHz 下推理，随后导出 96 kHz、24-bit 双声道 WAV；其输出不等同于 MR Remove 结果。
- 所有导出均为至少 96 kHz、24-bit PCM WAV，采用[日本音频协会 Hi-Res Audio 数字格式定义](https://www.jas-audio.or.jp/english/hi-res-logo-en)中的常用数值门槛。升采样不会产生输入或模型中原本不存在的频谱细节，本项目也不宣称获得 Hi-Res Audio Logo 认证。
- 输出路径不能覆盖任何输入文件。按 `Ctrl+C` 可取消命令行任务。
- 模型权重不会包含在 Python 包或独立程序中。
- 合成测试只能说明实现没有明显回归，最终效果应以同一素材的试听对比为准。

## 技术文档

算法、架构、测试和发布说明已移至 [docs/](docs/README.md)：

- [架构与数据流](docs/architecture.md)
- [参考引导人声提取](docs/reference-removal.md)
- [完整舞台实现](docs/full-stage.md)
- [AI 音轨分离实现](docs/neural-separation.md)
- [开发、测试与发布](docs/development.md)

## 致谢与许可

- [Vocal-Extractor](https://github.com/IamYei/Vocal-Extractor)：为频域人声提取方向提供启发。
- [Ultimate Vocal Remover GUI](https://github.com/Anjok07/ultimatevocalremovergui)：AI 处理流程参考其 MDX-Net 管线。
- [TRvlvr/model_repo](https://github.com/TRvlvr/model_repo)：提供 MDX-Net 模型文件；模型许可与致谢要求以各发布页为准。

本项目以 [AGPL-3.0-or-later](LICENSE) 发布。PySide6-Fluent-Widgets 开源版本使用 GPLv3，商业使用前请确认其上游许可。
