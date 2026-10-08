---
name: acorn-zh
description: Acorn 图像编辑软件自动化中文汉化、增量翻译与安全注入 Skill。支持版本更新后的自动 diff 比对、术语对齐、占位符防闪退校验、3文件微量备份还原与原生重签。
---

# Acorn 图像编辑软件 AI 增量本地化流水线

本 Skill 专为 macOS 原生图像编辑软件 **Acorn (Flying Meat Inc.)** 设计。完全基于本地化字典与确定性安全工具，不再进行复杂的单文件菜单打包，由 AI Agent 直接负责词条 diff 扫描、增量翻译补齐、就地安全修改与一键还原。

---

## 一、 核心资产与工具路径

* **项目根目录**：`/Users/YPJCoding/acorn-zh-hans`
* **术语约束库**：`termbase.json`（严格约束高频 UI 名词、动词及标点规则）
* **核心永久字典**：`translations/zh-Hans.json`（包含 canonical 规范词条与 exact 精确词条）
* **确定性安全引擎**：`core/acorn_tool.py`（负责 diff 提取、占位符校验、3 文件微量备份、plist 注入与安全重签）
* **目标应用默认路径**：`/Applications/Acorn.app`

---

## 二、 核心命令手册

在终端或通过 Agent 执行以下命令：

```bash
# 1. 检查目标 Acorn 状态（是否安装、版本、build、签名是否正常、是否已有备份）
python3 core/acorn_tool.py status --app /Applications/Acorn.app

# 2. 扫描与计算增量 Diff（列出所有尚未汉化的 Key，附带德/法/西/意对照参考与占位符检查）
python3 core/acorn_tool.py diff --app /Applications/Acorn.app

# 3. 提取未翻译列表到 JSON 文件（供批量翻译处理）
python3 core/acorn_tool.py diff --app /Applications/Acorn.app --output /tmp/acorn_pending.json

# 4. 安全注入汉化并重签生效（自动完成 3 文件备份、plist 配置与 ad-hoc 签名）
python3 core/acorn_tool.py apply --app /Applications/Acorn.app

# 5. 一键干净还原为官方原版（自动恢复 3 个原文件、清理注入资源、验证原厂签名）
python3 core/acorn_tool.py restore --app /Applications/Acorn.app
```

---

## 三、 Agent 增量翻译与更新工作流 (SOP)

当用户提出 **“Acorn 更新了，帮我增量汉化”** 或 **“补齐未翻译的词条”** 时，Agent 按照以下标准工序执行：

### Step 1: 扫描状态与提取 Diff
1. 检查 Acorn 是否已退出；
2. 运行 `python3 core/acorn_tool.py diff --app /Applications/Acorn.app --output /tmp/acorn_diff.json`；
3. 读取 `/tmp/acorn_diff.json`，查看有多少个新增/未翻译的词条。

### Step 2: 参照术语库与上下文进行翻译
1. **查阅 `termbase.json`**：确保核心术语一致（如 `Canvas` -> `画布`, `Selection` -> `选区`, `Layer Mask` -> `图层蒙版`, `Flatten Image` -> `拼合图像`）。
2. **查阅上下文对照（Refs）**：条目中提供了德语（de）、法语（fr）、西班牙语（es）的对应翻译，利用多语言对照准确判断词性（如 `Crop` 是动词“裁剪”还是名词“裁剪区”）。
3. **占位符防闪退校验（绝对铁律）**：
   * 原文中若有 `%@`、`%d`、`%1$@`、`%f` 等占位符，译文中**必须 100% 完整保留**，数量与类型必须严格对齐！
   * 原文中包含换行符 `\n` 时，译文也必须保持完全一致的换行数。

### Step 3: 更新主字典 `translations/zh-Hans.json`
通过 Python 脚本或直接编辑 JSON，将新翻译的条目以 `{ "Key": "译文" }` 追加到 `translations/zh-Hans.json` 的 `canonical`（常规）或 `exact`（特定完整匹配）下。

### Step 4: 确定性安全注入
运行：
```bash
python3 core/acorn_tool.py apply --app /Applications/Acorn.app
```
`apply` 会在写入前再次自动对全量字典运行 `validate_pair` 占位符拦截，确保不会引入闪退风险；然后完成微量备份（仅 26MB，位于 `Resources/.acorn-zh-backup/`）并重签名。

### Step 5: 验证并反馈
运行 `python3 core/acorn_tool.py status --app /Applications/Acorn.app`，向用户确认版本、生效词条数和签名状态。
