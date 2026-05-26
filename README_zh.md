# CLI Chat Exporter

[English](README.md)

CLI Chat Exporter 提供 `cce` 命令，用于把本机 AI 助手聊天记录导出为 Markdown 和 HTML 归档。

当前支持 Codex、Cursor、OpenClaw。本 npm CLI 只导出当前本机用户可读取的聊天历史，不获取 sudo 权限，不读取其他用户目录。

## 效果预览

| 格式 | 简略版 | 详细版 |
| --- | --- | --- |
| HTML | ![HTML 简略版导出](assets/screenshots/concise-html.png) | ![HTML 详细版导出](assets/screenshots/detail-html.png) |
| Markdown 预览 | ![Markdown 简略版预览](assets/screenshots/concise-md.png) | ![Markdown 详细版预览](assets/screenshots/detail-md.png) |

## 安装

```bash
npm install -g @benryoung/cli-chat-exporter
```

要求：

- Node.js 20 或更新版本。
- 可用的 Python 3，命令为 `python3` / `python`，或通过 `CCE_PYTHON` / `runtime.python` 配置。
- 自动发现本机用户记录支持当前用户的原生系统路径；Windows 下当前临时仅自动发现 Codex。

## 快速开始

```bash
cce help
cce doctor
cce config init # 交互式初始化,可启用定时任务
cce export --source all --format both --output ~/AIChatRecords # 手动备份
```

默认输出目录为 `~/AIChatRecords`。默认会同时生成简略版和详细版。

## 输出内容

支持来源：

- Codex
- Cursor
- OpenClaw

支持格式：

- Markdown
- HTML
- 同时导出两种格式

每个会话会生成：

- `*_concise`：适合阅读和归档的主要对话内容。
- `*_detail`：包含 metadata、tool calls、events 和诊断上下文的详细版本。

## 常用命令

```bash
cce help
cce version
cce doctor
cce export --source all --format both --output ~/AIChatRecords
cce config get
cce config init
cce service start
cce service status
cce service stop
```

## 隐私与权限

npm CLI 固定为当前用户范围：

- 不提供 `--user` 参数。
- 不请求 sudo。
- 不写 sudoers。
- 不读取其他用户 home 目录。
- 不上传聊天记录，所有处理都在本机完成。

## 高级 Python 用法

底层 Python 导出器仍保留显式用户范围参数，供本机管理员场景使用。例如：

```bash
sudo /path/to/python /path/to/chatManager/export_session.py --user all --format both --output /path/to/AIChatRecords
```

该能力不会进入 npm CLI 配置模型。

## 开发

```bash
npm test
npm run pack:check
```

## 许可证

MIT
