# 开发与贡献

<p align="left">
  <strong>简体中文</strong> · <a href="en/CONTRIBUTING.md">English</a>
</p>

本文档阐述 Purivox 项目的开发环境搭建、架构分层规则、代码风格规范、多语言维护流程、测试验证与持续集成/发布指南。

## 开发环境搭建

项目使用 [uv](https://docs.astral.sh/uv/) 作为包管理与隔离环境工具。克隆仓库后，在根目录执行依赖同步：

```bash
uv sync --locked
```

Python 解释器版本由 `.python-version` 统一指定，`uv` 将自动配置并初始化隔离虚拟环境。

验证本地环境运行状况：

```bash
uv run --locked purivox                                        # 启动桌面图形界面
QT_QPA_PLATFORM=offscreen uv run --locked purivox --selftest   # 无头模式执行自检冒烟测试
```

依赖变更使用 `uv add <package>`、`uv add --dev <package>` 或 `uv add --group deploy <package>`，并将同步更新的 `pyproject.toml` 与 `uv.lock` 一同提交。

请勿在该环境中安装其他可能导出同名 `qfluentwidgets` 命名空间的第三方 Qt 组件，以防符号解析冲突。

## 模块分层准则

系统依赖方向严格自顶向下：
- `src/shared/` 作为底层共享基础设施，严禁导入 `app`、`entrypoints` 或任何 `features/`；
- 各业务功能包（`src/features/`）自包含业务页面、数据模型与处理逻辑，相互之间严禁跨包导入；
- 外壳层（`src/app/` 与 `src/web/`）负责多模块协同编排，严禁反向导入 `entrypoints/`；
- 两个或以上功能包共享的算法、数据类型或配置常量必须下沉至 `src/shared/`，严禁通过重导出建立隐式依赖。

分层边界由 `tests/test_architecture.py` 静态检查，违背分层约束将导致构建与测试失败。

## 编码规范

### Python 规范

- 模块顶部统一使用 `from __future__ import annotations`，所有函数签名与数据结构必须具备完整的类型标注；
- 任务与配置数据模型优先使用不可变数据类（`@dataclass(frozen=True, slots=True)`），固定枚举集合使用 `StrEnum`；
- 模块日志统一通过 `logging.getLogger(__name__)` 获取，禁止吞咽非预期异常；
- 代码格式与静态检查遵循 Ruff 规则集（行宽限制 100 字符，启用 E、F、I、UP、B、SIM、RUF 规则）。

### Qt 与桌面端交互

- 页面组件仅负责界面渲染与事件发射，后台异步任务统一由 `app/job_presenter.py` 协调并交由 `app/job_runner.py` 调度执行；
- 跨线程接收信号的槽函数必须显式标注 `@Slot(<type>)`，确保 Qt 运行时正确派发排队连接；
- 优先采用 Qt 推荐的最佳实践（如表格数据使用 `QAbstractTableModel` 与 Fluent `TableView` 结合，网络请求使用 `QNetworkAccessManager`，文件校验写入使用 `QSaveFile`）；
- 单一功能包内的独立控件应进行组件化拆分。

### 音频处理与内存管理

- 长音频处理必须结合 `create_pcm_audio` 与流式分块循环（分块常量统一使用 `shared.audio.BLOCK_FRAMES`），禁止直接将全文件载入普通内存数组；
- 密集计算循环中须定期调用 `CancellationToken.raise_if_cancelled()` 响应任务取消；
- 音频写出统一使用 `write_wav_atomic` 原子写入；
- 导出文件严格保持输入音频的原生采样率与格式位深（8/16-bit PCM 输出为 16-bit PCM，其余及有损格式输出为 24-bit PCM），严禁进行无物理意义的升采样。

### DSP 算法演进准则

- 所有对消与分轨算法的输出信号仅允许从原始混音中重构提取，禁止将参考信号或其反相波形直接写入输出；
- DSP 算法改动须通过量化指标验证（使用 `tools/eval_cancellation.py` 与 `tools/eval_stems.py` 执行基线比对），并配合实际现场素材进行试听核对。

## 多语言国际化（i18n）

多语言文案源文件为 Qt Linguist XML 格式（`src/resources/i18n/*.ts`），编译生成的 `*.qm` 二进制文件供应用运行时加载：

```text
src/resources/i18n/zh_cn.ts   src/resources/i18n/zh_cn.qm
src/resources/i18n/zh_tw.ts   src/resources/i18n/zh_tw.qm
src/resources/i18n/en_us.ts   src/resources/i18n/en_us.qm
src/resources/i18n/ja_jp.ts   src/resources/i18n/ja_jp.qm
src/resources/i18n/ko_kr.ts   src/resources/i18n/ko_kr.qm
```

1. **键值维护**：`.ts` 文件按上下文键名（Key）组织。新增文案前应优先复用现有词条；
2. **正体中文规范**：`zh_tw` 遵循台湾正体中文技术术语习惯（如「檔案」、「取樣率」、「辨識」、「快取」等）；
3. **编译要求**：修改任一 `.ts` 后，须执行重新编译并将更新后的 `.ts` 与 `.qm` 一并提交：

```bash
for locale in zh_cn zh_tw en_us ja_jp ko_kr; do
  uv run --locked pyside6-lrelease "src/resources/i18n/$locale.ts" \
    -qm "src/resources/i18n/$locale.qm"
done
```

4. **完整性约束**：测试套件会校验五种语言的键集合完全一致，且不存在过期 `.qm` 文件。

## 构建清单配置（三处同步）

新增源码文件或目录时，须检查以下三处打包配置，防止发布包遗漏组件：
1. `pyproject.toml` 中的 `[tool.hatch.build.targets.wheel] packages`；
2. `pyproject.toml` 中的 `[tool.pyside6-project].files`；
3. `pysidedeploy.spec` 中的 `include-package` 清单。

`tests/test_packaging.py` 会自动核对源码目录与配置清单的对应关系。

## 本地验证流程

在提交代码前，请执行完整的本地自动化测试与静态检查（Qt 测试须在离屏环境下运行）：

```bash
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
QT_QPA_PLATFORM=offscreen uv run --locked pytest
QT_QPA_PLATFORM=offscreen uv run --locked purivox --selftest
uv build
```

针对长音频进行的 15 分钟高负载基准测试（检查内存泄漏与接缝连续性，需显式开启）：

```bash
QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/benchmarks --runslow
```

修改文档后，须确保文档链接与双语对称性测试通过：

```bash
QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/test_documentation.py
```

## Git 提交规范

- **Commit 标题**：格式为 `type(scope): description`（小写祈使句，无句号）。常见类型：`feat`、`fix`、`perf`、`refactor`、`docs`、`ci`、`build`、`chore`；
- **Commit 正文**：建议使用英文清晰说明改动背景、关键约束与技术选型原因，按 80 字符列宽折行；
- **更新日志**：面向用户的实质性改动须同步更新 `CHANGELOG.md` 中对应版本小节（中英双语对照）。

## 发布流程（维护者参考）

1. 更新 `src/app/version.py` 中的 `__version__`；
2. 在 `CHANGELOG.md` 顶部新增对应的版本小节：`## v<版本> — <日期>`；
3. 提交变更并打上带注释的版本标签：

```bash
git tag -a v1.0.0 -m "Purivox v1.0.0"
git push origin main --follow-tags
```

GitHub Actions 将自动触发 `release.yml`，执行质量检查、跨平台编译（Linux、Windows、macOS arm64/x86_64）并发布 Release 工件与校验和。AUR 软件包在 GitHub Release 完成后由维护者执行 `deployment/aur/publish.sh` 更新。
