# 开发与贡献

<p align="left">
  <strong>简体中文</strong> · <a href="en/CONTRIBUTING.md">English</a>
</p>

这份文档写给要改这个仓库的人：怎么把环境跑起来、代码该放在哪、改完怎么验证、提交要写成什么样。
算法和架构本身见[架构与数据流](architecture.md)与各功能文档。

## 准备环境

项目用 uv 管理 Python、隔离环境和锁文件。装好 uv 后，在仓库根目录安装锁定的运行时依赖和默认开发
依赖，Python 版本由 `.python-version` 决定，uv 会自动取：

```bash
uv sync --locked
```

跑起来确认环境没问题：

```bash
uv run --locked purivox                                        # 图形界面
QT_QPA_PLATFORM=offscreen uv run --locked purivox --selftest   # 管线冒烟，无需显示器
```

改依赖用 `uv add <包名>`、`uv add --dev <包名>` 或 `uv add --group deploy <包名>`，
并把同步更新的 `pyproject.toml` 与 `uv.lock` 一起提交。

不要在这个环境里再装别的会导出 `qfluentwidgets` 的 PyQt / PySide Fluent 组件。项目指定的是
`PySide6-Fluent-Widgets[full]`，装第二个会让导入解析到哪一份变得不确定。

## 代码放在哪里

依赖只能向下流：`shared` 不导入我们的任何东西，功能包之间不互相导入，`app` 和 `web` 都不导入
`entrypoints`。`tests/test_architecture.py` 解析 import 强制这条规则，越界会让构建失败。

- 一个新功能就是 `src/features/` 下的一个新目录，自带页面、模型和处理逻辑。
- 两个功能都要的东西，或者 GUI 与 CLI 都要的东西，向下沉到 `shared` 定义一次再引用，
  例如 `shared.audio.BLOCK_FRAMES`、`shared.audio.AUDIO_EXTENSIONS`、
  `shared.jobs.SIGMA_CHOICES`、`shared.i18n.SUPPORTED_LANGUAGES` 和 `shared.logging.LOG_LEVELS`。
- 需要联合多个功能的编排放在 `app`，不要为了复用让功能包互相导入。
- 公共数据模型按使用方归属：被多个功能消费的放 `shared`，只在一个功能内部用的留在原地，
  不得为了方便从别的功能再导出。

分层的完整说明和每层职责见[架构与数据流](architecture.md)。

## 代码约定

### Python

- 新模块使用 `from __future__ import annotations` 和完整类型标注。
- 可变参数少的任务模型优先用 `frozen=True, slots=True` 数据类，固定字符串集合用 `StrEnum`。
- 日志通过 `logging.getLogger(__name__)` 写入；只有明确记录的降级路径可以忽略局部失败。
- Ruff 行宽 100，启用 E、F、I、UP、B、SIM 和 RUF 规则，E501 由格式化与评审控制。

### Qt

- 后台任务统一由 `app/job_presenter.py` 协调页面状态，再交给 `app/job_runner.py` 管理线程；
  页面和业务管线不得自行创建线程。
- 跨线程接收信号的槽用 `@Slot(<类型>)` 标注（worker → `JobRunner` → `JobPresenter`），
  让 Qt 按声明的签名派发排队连接。
- Qt 已经处理好的问题优先用 Qt 的方案：可编辑表格用 `QAbstractTableModel` + `TableView`，
  不要用 `QTableWidget` 逐格填 item；HTTP 用 `QNetworkAccessManager`（系统代理、跳转、超时、
  进度、`abort()`）；需要先校验再写入时用 `QSaveFile`；路径用 `QStandardPaths`。
  标准库已经等价或更好的地方保持不变（`hashlib`、`tempfile` + `numpy.memmap`、
  argparse 子命令、DSP 线程池）。
- 页面里的独立交互控件拆成同功能包内的小模块，例如试听跳转控件位于
  `reference_removal/preview.py`。

### 音频与内存

- 长音频用 `create_pcm_audio` 与分块循环（块大小取 `shared.audio.BLOCK_FRAMES`），
  不要把整个文件复制到普通内存数组；映射页用 `shared.audio.release_mapped_pages()` 释放。
- 可取消循环必须定期调用 `CancellationToken.raise_if_cancelled()`，且不得忽略取消异常。
- 输出用 `write_wav_atomic`，不要直接覆盖目标文件。
- 导出规格跟随输入文件：`AudioData` 同时携带解码源的 `sample_rate` 与 `bit_depth`，
  `resample_audio` 与 `stereo()` 逐级传递，`write_wav_atomic` 与 `analyze_audio` 直接读取，
  不再接收格式参数。`WAV_BIT_DEPTHS` 为 `(16, 24)`：8-bit 与 16-bit PCM 输入写出 16-bit，
  更宽的 24/32-bit PCM、浮点以及所有有损格式写出 24-bit。不存在导出规格下限，
  也不得为凑规格而向上重采样。

### DSP

所有用户可选的处理路径都只能从现场原混音重建，不得把音源独有的内容或它的反相写进结果。
DSP 改动按测量接受，不按论证接受：先过自动化检查，再对固定的真实素材导出可以直接试听对比的版本。
技术检查结果不应写成“已确认听感”。

## 界面文案与翻译

界面字符串以 Qt Linguist 的 `.ts`（XML）为可编辑来源，编译产物 `.qm` 由 `QTranslator` 加载：

```text
src/resources/i18n/zh_cn.ts   src/resources/i18n/zh_cn.qm
src/resources/i18n/en_us.ts   src/resources/i18n/en_us.qm
src/resources/i18n/ja_jp.ts   src/resources/i18n/ja_jp.qm
src/resources/i18n/ko_kr.ts   src/resources/i18n/ko_kr.qm
```

`.ts` 按键索引而非按原文索引：`<source>` 是 `nav_mr` 这样的短标识，`<translation>` 是各语言文本，
四个文件同属 `Purivox` 这一个 context。因此改中文不会牵动其他语言的条目，`pyside6-lupdate`
也不适用（它按源码中的字面量提取），翻译条目由人工维护。

动手前先在四个 `.ts` 里搜一遍：桌面端已经给大多数状态起过名字（`warn_no_song`、
`stage_need_sources`、`preview_empty`、整套 `home_*`），复用现成的键能让四种语言一次就对。

改过任一 `.ts` 都要重新编译，并把 `.ts` 与 `.qm` 一起提交：

```bash
for locale in zh_cn en_us ja_jp ko_kr; do
  uv run --locked pyside6-lrelease "src/resources/i18n/$locale.ts" \
    -qm "src/resources/i18n/$locale.qm"
done
```

增加、删除或重命名翻译键时必须同步修改四个 `.ts`。测试会检查键集合完全一致、`.qm` 与 `.ts`
未过期，并且源码中出现的每个字面量键都存在于所有语言。调用 `tr(key, **values)` 时不得依赖
“未知键返回键名”的回退行为。

语言是应用级状态：`shared.i18n.install_language()` 安装对应语言的 `QTranslator`，`tr()` 经
`QCoreApplication.translate()` 查表，因此任务对象和处理管线不携带语言参数。GUI 在设置页切换语言时
重新安装并调用各页面的 `retranslate()`，CLI 则在启动时按 `--lang` 安装一次。

配置由 `src/shared/config.py` 中的 QConfig 单例管理。改持久化选项时要同时考虑默认值、验证器、
页面重译和测试。

## 新增文件要登记三处

新增源码目录或文件时检查三个发布清单，漏掉任一处都可能开发环境正常、而 wheel 或独立程序缺文件：

1. `pyproject.toml` 的 wheel 包列表；
2. `pyproject.toml` 的 `[tool.pyside6-project].files`；
3. `pysidedeploy.spec` 的 `include-package` 或相应包含项。

`tests/test_packaging.py` 会自动比较所有 `src/**/*.py` 与 `[tool.pyside6-project].files`，
并拒绝遗漏或失效条目；新增顶层包时仍需人工确认 wheel 与 Nuitka 的包清单。

## 浏览器前端

`web/` 是 Vite + React 前端，跑的是同一份 `src/`：`predev` / `prebuild` 会把 Python 树打包成
`purivox-src.zip` 并生成翻译 JSON，所以改完 Python 或 `.ts` 词条后重新跑一次即可。

```bash
cd web && bun install
bun run dev        # http://localhost:5173/
bun run check      # tsc + Biome + 分层检查，build 会先跑它
```

前端的分层与 Python 端同构，同样由 `scripts/check-architecture.mjs` 强制。改动 DSP 时注意
Pyodide 没有 pthread，`process_audio` 因此有串行分支，
`tests/features/reference_removal/test_dsp_execution.py` 要求两条路径输出一致。
细节见[浏览器版（WebAssembly）](web.md)。

## 验证改动

Qt 测试必须用离屏平台，conftest 会设置它：

```bash
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
QT_QPA_PLATFORM=offscreen uv run --locked pytest
QT_QPA_PLATFORM=offscreen uv run --locked purivox --selftest
uv build
```

改了 DSP 还要给出测量，而不是说明：

```bash
uv run --locked python tools/eval_cancellation.py --save baseline.json    # 改动前
uv run --locked python tools/eval_cancellation.py --compare baseline.json # 改动后
```

慢速基准要显式开启，用 15 分钟、44.1 kHz 双声道音频检查参考对消的输出长度、接缝和峰值常驻内存，
内存上限 2 GiB：

```bash
QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/benchmarks --runslow
```

合成信号指标只用来发现实现回归，不构成对真实音乐的结论。

### 测试放在哪

`tests/` 与 `src/` 路径一一对应，所以改动的测试就在镜像位置：DSP 与对齐回归在
`tests/features/reference_removal/`，时间线与匹配在 `full_stage/`，模型下载 / 校验 / 取消在
`neural_separation/`，运行器与协调器生命周期以及 pytest-qt 的界面测试在 `tests/app/`，
公共音频、任务协议和控件在 `tests/shared/`。

Pytest 用 `importlib` 导入模式，允许不同目录使用与源码对应的相同测试文件名而不发生模块碰撞。
另有三道仓库级闸门：`test_architecture.py`（导入边界）、`test_packaging.py`（发布清单）、
`test_documentation.py`（README 索引、文档翻译配对、内部链接）。重命名文档时同步改索引和引用，
不要留下失效链接等人发现。

没有测试会访问真实主机：模型仓库与更新检查的测试把 `catalog.MODEL_BASE_URL` 和
`updates.RELEASES_API` 指向本地服务器。

### CI 会跑什么

Pull Request 和 `main` 上的提交由 `.github/workflows/build.yml` 触发，它只是一层薄壳，
调用 `.github/workflows/common.yml` 跑完整流水线：先过上面那套质量检查，再并行构建
Linux、Windows 与 macOS 产物。质量检查只在 Ubuntu 上跑一遍，Windows 与 macOS 任务只产出二进制。
工件保留 14 天，同一分支有新提交时旧任务会被取消。

## 提交

- **主题**写成 `type(scope): 改了什么`，祈使句、小写、不加句号。在用的类型有 `feat`、`fix`、
  `perf`、`refactor`、`docs`、`ci`、`build`、`chore`；scope 是区域（`dsp`、`ui`、`web`、`audio`、
  `i18n`、`full-stage`、`settings`、`shared`、`release`），横跨整个仓库的改动可以省略。
- **正文**用英文散文，按 80 列折行，说明这个改动为什么长这样：问题是什么、哪个约束定了这个设计、
  否决了什么以及为什么。不是把 diff 重述一遍，也不是罗列要点。
- 一次提交做一件事。翻译改动要带上重新编译的 `.qm`，依赖改动要带上 `uv.lock`。

仓库里的既有提交就是样例：

```text
perf(dsp): build the cancellation chain in place instead of a temporary per step
fix(web): merge Fluent class names instead of concatenating them
refactor(dsp): run the pipelines where there is no Qt and no threads
```

面向用户的改动还要在 `CHANGELOG.md` 里对应版本的小节补一条。每个已发布版本一节，中英双语——
发布流程会把与标签同名的那一节发成 Release 说明，应用内“检查更新”弹窗显示的也是这段文本。

## 打包与发布（维护者）

日常贡献不需要执行这一节。

`uv build` 把 wheel 与 sdist 写到 `dist/`，版本号以 `src/app/version.py` 为唯一来源，
由 Hatch 在构建时读取；ONNX 权重在忽略列表里，不进 wheel 或源码包。独立程序由 `pyside6-deploy`
封装 Nuitka 构建（`uv sync --locked --group deploy`），Linux 与 Windows 是 onefile 的
`dist/Purivox.bin` / `Purivox.exe`，macOS 是应用包 `dist/Purivox.app` 且只构建 arm64——锁文件里
ONNX Runtime 的 macOS wheel 只有 arm64 一种。三者都内含 Python 与 Qt，不含模型权重。产物由 CI
构建，发布前应实际启动一次，确认解包路径下的资源文件仍能被找到。

发布由标签驱动，除打标签外没有手动步骤：

1. 更新 `src/app/version.py` 里的 `__version__`；
2. 在 `CHANGELOG.md` 顶部新增一节，标题写成 `## v<版本> — <日期>`；
3. 提交后打上同名标签并推送。

```bash
git tag -a v1.0.0 -m "Purivox v1.0.0"
git push origin main --follow-tags
```

标签推送后 `release.yml` 先跑完 `common.yml` 的整条流水线，`publish` 任务再把这一次构建出来的
产物发布出去，并重新生成一份扁平的 `SHA256SUMS`。质量检查的第一步会核对标签与
`src/app/version.py` 是否一致，不一致就在几分钟内失败，不会等编译跑完一个小时。带后缀的标签
（如 `v1.1.0-rc1`）发布为 pre-release，`releases/latest` 不会返回它。重新运行同一个标签的构建
会覆盖上传资产，不会新建 Release。

AUR 包（`deployment/aur/`）在发布之后由人运行 `deployment/aur/publish.sh` 推送，从不由 CI 做：
它把 `purivox-bin` 重新指向这次发布的 `.deb`，本地构建一次作为检查，再推 `PKGBUILD` 与 `.SRCINFO`。
