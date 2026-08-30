# 架构与数据流

<p align="left">
  <strong>简体中文</strong> · <a href="en/architecture.md">English</a>
</p>

## 设计目标

Purivox 将界面、功能实现和公共基础设施分开。GUI 与 CLI 只负责收集参数、报告进度和展示结果，实际处理由可独立调用的任务函数完成。这样可以让桌面端和命令行复用同一实现，也便于在不启动界面的情况下测试音频管线。

## 分层结构

```text
src/entrypoints/                 程序入口，只负责启动 GUI 或解析 CLI
src/app/                         主窗口、任务运行器和跨功能编排
src/features/                    各功能自包含的页面、模型与处理逻辑
├── reference_removal/           单曲参考对消、试听控件与 DSP
├── full_stage/                  完整舞台分析与时间线模型
├── neural_separation/           MDX-Net 模型、模型仓库与推理
├── home/                        首页
└── settings/                    设置页
src/shared/                      音频、频谱、任务参数校验、配置、日志、任务协议和通用控件
src/resources/                   翻译和模型规格等只读资源
```

依赖方向为：

```mermaid
flowchart LR
    entry["程序入口<br/>src/entrypoints"] --> app["应用编排<br/>src/app"]
    app --> feature["功能模块<br/>src/features"]
    app --> shared["公共模块<br/>src/shared"]
    feature --> shared
```

`tests/test_architecture.py` 通过抽象语法树检查以下边界：

- `shared` 不得导入 `app`、`entrypoints` 或任何 `features`。
- 功能包不得导入 `app`、`entrypoints` 或其他功能包。
- `app` 不得反向导入 `entrypoints`。
- 需要联合多个功能的逻辑放在 `app`。例如完整舞台渲染同时使用时间线分析与参考对消，因此位于 `src/app/full_stage_processing.py`。

公共数据模型按“由谁消费”归属，而不是按最早出现的位置归属。例如 `AudioStats` 同时用于单曲和完整舞台，定义在
`shared.audio`；`ReferenceJob` 只服务单曲参考对消，保留在 `features/reference_removal`。功能模块之间不通过
重导出公共类型建立隐式依赖。

同一条规则适用于代码：被多个功能重复实现的取值和算法下沉到 `shared`，而不是在功能之间互相导入。
单曲与完整舞台任务共用 `shared.jobs.validate_reference_settings()` 校验强度、统计窗口和中置处理组合；
两者的起音特征共用 `shared.dsp.log_flux_bands()`；文件对话框过滤器与自动查找的扩展名共用
`shared.audio.AUDIO_EXTENSIONS`。

## 任务执行模型

每个页面只发出开始和取消信号，不直接控制线程。`MainWindow` 根据页面参数建立不可变任务对象，并把处理函数交给
`JobPresenter`。协调器负责页面 running 状态、进度提示与结果展示，并把后台执行交给 `JobRunner`。运行器独占
`QThread` 和 `ProcessingWorker` 的生命周期，保证同一窗口一次只有一个任务；`ProcessingWorker` 只负责把普通
Python 调用适配为 Qt 信号。运行器只在线程对象完成 deferred delete 后发出自己的 `finished`，避免窗口关闭或测试
作用域退出与 Qt 对象析构竞态。主窗口因此只保留导航、任务参数构造和关闭协调。

```mermaid
flowchart LR
    page["GUI 页面"] -->|参数| job["不可变任务对象"]
    job --> window["MainWindow"]
    window --> presenter["JobPresenter<br/>页面状态与结果展示"]
    presenter --> runner["JobRunner"]
    runner -->|拥有| worker["QThread + ProcessingWorker"]
    worker --> pipeline["处理函数"]
    cli["CLI"] -->|同步调用| pipeline
    pipeline --> result["处理结果"]
    result -->|信号| page
    cancel["取消请求"] -.-> token["CancellationToken"]
    token -.-> pipeline
```

CLI 创建相同的任务数据类并同步调用同一处理函数。`SIGINT` 会设置 `CancellationToken`；各个解码、重采样、分析、推理和写出循环定期调用 `raise_if_cancelled()`，因此取消是协作式的。

## 音频数据与内存管理

公共音频类型 `AudioData` 使用 `[声道, 帧]` 排列的 `float32` 平面数据。长音频不常驻普通 NumPy 数组，而是写入临时
`np.memmap`：

- 解码、统计、重采样、写出和多数复制操作以 262,144 帧为一块（`shared.audio.BLOCK_FRAMES`）。
- libsndfile 无法读取的格式回退到 Qt Multimedia 解码。
- 重采样使用 soxr 的高质量流式接口。
- 单声道输入会扩展为双声道；多于两个声道时处理前取前两个声道。
- 临时音频通过 `cleanup()` 关闭并删除；长循环可调用 `release_pages()` 释放已处理映射页。

`shared.audio.analysis` 提供分块复制、峰值/RMS 统计和跨工作流共用的 `AudioStats`。块大小只在
`shared.audio.BLOCK_FRAMES` 定义一次，由所有流式循环共用，避免每条管线各自维护一套容易漂移的实现。
映射页的查找与释放同样只有 `shared.audio.release_mapped_pages()` 一份实现，`AudioData` 与参考对消
的分块循环都调用它。

WAV 写出先生成同目录临时文件，成功后使用 `os.replace` 原子替换目标。取消或异常不会留下半写入的正式输出。

## 三条处理管线

```mermaid
flowchart TB
    input["音频输入"] --> choice{"工作流"}
    choice -->|单曲参考对消| mr["对齐参考音源<br/>参考掩码对消"]
    choice -->|完整舞台| stage["多音源匹配<br/>按时间线分段对消"]
    choice -->|AI 音轨分离| ai["模型分块推理<br/>计算人声与背景"]
    mr --> mrout["至少 96 kHz / 24-bit 人声 WAV"]
    stage --> stageout["至少 96 kHz / 24-bit 整场 WAV"]
    ai --> aiout["两个 96 kHz / 24-bit WAV"]
```

### 单曲参考对消

```text
读取两段音频 → 双声道化 → 参考重采样 → 可选时间对齐
→ 参考对消 → 统计 → 原子写出
```

输出长度始终跟随待处理音频；歌曲音源较短时，其结束后的区域按静音参考处理并保留原音，不再截短结果。处理完成后，低于 96 kHz 的结果升采样到 96 kHz，再写出 24-bit WAV；更高的原始采样率保持不变。

### 完整舞台

```text
整场与音源提取指纹 → 独立匹配 → 生成和人工校正时间线
→ 复制整场原音 → 对匹配片段逐段对齐并对消 → 淡入淡出拼接 → 原子写出
```

未匹配区间来自整场原音的副本，因此不会因识别失败而补零或缩短。
整场内部处理保持舞台 / 现场音频的采样率，最终导出同样采用至少 96 kHz、24-bit PCM WAV。

### AI 音轨分离

```text
读取并双声道化 → 重采样到 44.1 kHz → 查找或下载模型
→ MDX-Net 分块推理 → 背景 = 混音 - 人声
→ 升采样到 96 kHz → 写出两个 24-bit WAV
```

Hi-Res 在这里描述导出文件的采样率与位深，不代表低采样率输入或 44.1 kHz 模型推理获得了新的高频信息，也不代表项目获得 Hi-Res Audio Logo 认证。

## 配置、翻译与日志

- 配置由 QFluentWidgets 的 `QConfig` 持久化。
- 翻译使用 Qt 原生体系：`src/resources/i18n/*.ts`（Qt Linguist XML）经 `pyside6-lrelease` 编译成
  `*.qm`，由 `QTranslator` 加载并安装到 `QCoreApplication`。键按标识符组织，四种语言的键集合必须完全一致。
- `shared.i18n.tr(key, **values)` 通过 `QCoreApplication.translate()` 取当前安装语言的文本，再填充
  `{name}` 占位符；未知键返回键名本身。语言是应用级状态，任务对象不再携带语言字段。
- 日志使用单行格式 `日期 时间 [级别] 模块: 消息`，Qt 与 FFmpeg 消息也会进入统一日志系统。
- GUI 切换语言时，各页面通过 `retranslate()` 更新控件文本和下拉列表。
- 各处理管线通过 `shared.progress.report_progress()` 统一翻译并生成 `ProgressEvent`，避免每个功能重复拼装进度协议。

## 错误边界

输入文件相同、输出覆盖输入、参数范围错误等可预期问题使用 `ValueError`、`KeyError` 或
`FileNotFoundError`。CLI 对这些错误返回状态码 2，未预期异常返回 1，取消返回 130；GUI 则通过工作线程信号显示错误提示。

时间对齐失败是少数允许降级的情况：处理管线记录警告并使用原始时间线继续运行。取消异常不得被吞掉。
