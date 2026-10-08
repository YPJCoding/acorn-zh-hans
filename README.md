# Acorn 图像编辑软件 · AI 增量本地化流水线

基于 AI Agent 全托管的 macOS 原生图像编辑软件 **Acorn (Flying Meat Inc.)** 本地化工具。

放弃繁琐、臃肿的单文件菜单打包，采用 **“确定性安全工具 + 永久维护字典 + 术语对齐约束 + AI 增量翻译”** 架构。针对应用版本更新，能够自动提取 Diff、由 AI 补全增量翻译、就地安全修改，并随时可一键 100% 还原为原厂官方版本。

---

## 一、 核心架构设计

```
[ Acorn.app 更新 ]
        │
        ▼
[ core/acorn_tool.py diff ] ──> 提取未翻译条目（附带德/法/西多语言对照上下文与占位符检查）
        │
        ▼
[ AI Agent 增量翻译 ]      ──> 严格对齐 termbase.json 术语库，自动保留 %@ / %d 占位符
        │
        ▼
[ 更新 translations/zh-Hans.json ] ──> 词典资产永久保存，跨版本复用
        │
        ▼
[ core/acorn_tool.py apply ] ──> 占位符防闪退校验 -> 3文件微量备份 -> Info.plist注入 -> 保持metadata重签
        │
        ▼
[ 完美运行汉化版 Acorn ] (支持随时 restore 一键恢复原厂官方签名)
```

---

## 二、 关键资产与目录说明

* **`termbase.json`**：术语库基线（严格规范 Canvas/画布、Layer/图层、Layer Mask/图层蒙版、Flatten/拼合图像等核心概念）。
* **`translations/zh-Hans.json`**：永久维护的主字典（包含 `canonical` 基础词条与 `exact` 严格匹配词条，具备大小写折叠与快捷键/标点派生识别）。
* **`core/acorn_tool.py`**：轻量级、确定性 Python 核心引擎（零第三方依赖，纯 macOS 原生工具驱动）。
* **`SKILL.md`**：已注册至 `~/.agents/skills/acorn-zh`，支持在终端通过 AI Agent 全托管调用。
* **`legacy/`**：归档的历史单文件 Shell 菜单生成器与旧发布文件（如需分发给无 Python 环境的小白用户可查阅）。

---

## 三、 日常命令行指南

所有操作均支持直接在终端中手动执行，或由 AI Agent 自动调用：

### 1. 检查当前状态
```bash
python3 core/acorn_tool.py status --app /Applications/Acorn.app
```
输出目标 App 的版本、Build 号、当前是官方原版（`OFFICIAL`）还是已汉化（`LOCALIZED`）、签名有效性及备份状态。

### 2. 扫描并比对未翻译条目（Diff）
```bash
python3 core/acorn_tool.py diff --app /Applications/Acorn.app
```
扫描目标应用的所有语言资源并与主字典比对，输出汉化覆盖率，并打印未翻译词条及其德/法/西/意参考译文与 `%@` 等占位符要求。

若需导出待翻译清单供 Agent 处理：
```bash
python3 core/acorn_tool.py diff --app /Applications/Acorn.app --output /tmp/acorn_pending.json
```

### 3. 就地安全注入汉化
```bash
python3 core/acorn_tool.py apply --app /Applications/Acorn.app
```
* 自动在 `Contents/Resources/.acorn-zh-backup/` 保留 3 个关键原文件的微量备份（仅 26MB，不额外占用大磁盘空间）；
* 自动注入 `zh-Hans.lproj/Localizable.strings`；
* 注入 `Info.plist`（设置中文语言优先级，同时关闭 Sparkle 自动更新以避免破坏补丁）；
* 执行保留原有 Hardened Runtime 与 Entitlements 的精准本地签名；
* 重新校验应用签名。

### 4. 恢复官方原厂状态
```bash
python3 core/acorn_tool.py restore --app /Applications/Acorn.app
```
将 3 个备份原文件逐字节复原，清理注入资源与备份目录，验证原厂官方代码签名。

---

## 四、 运行自动化测试

验证核心引擎的安全性、备份完整性、签名正确性与 100% 还原度：

```bash
python3 -m unittest discover -s tests -p "test_core_tool.py" -v
```
