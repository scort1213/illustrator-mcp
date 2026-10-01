# Illustrator MCP 本地操作版

用于 Codex 等 MCP 客户端控制本机 Adobe Illustrator。已在 Windows + Illustrator 2024 (28.6.0) 完成实机和 Codex 对话入口主流程验收。

本地操作版已在 macOS + Illustrator 30.8.1 完成一轮真实 MCP 创建、编辑、保存、PNG 导出、关闭重开验收；本次未重新验收 Windows，macOS 的全屏 `view` 未调用。

本分支保留全部 9 个工具和任意可信 JSX。MCP 初始化指令、`run` 说明和设计提示统一要求：只做本地编辑与本地文件操作，不调用 Firefly、生成式 AI、云文档、在线素材、在线字体激活、浏览器登录或联网命令；本地能力缺失时直接说明，不改走云服务。Windows 与 macOS 使用相同指令。

这些是给调用助手的明确指令，不是脚本沙箱或网络拦截；`run` 不过滤脚本，不能保证调用者一定遵守。Adobe 软件自身的许可登录、后台联网，以及 AI 客户端的账号和服务不在本次范围内。新增规则的自动化验证与历史实机验收分别记录，不能相互替代。

- [Windows 安装与 Codex 配置](WINDOWS_CODEX_SETUP.md)
- [中文验收记录与尚未覆盖的边界](ACCEPTANCE_ZH.md)
- [安全机制与恢复约定](BOUNDARY_HARDENING.md)

下载此分支源码 ZIP 并解压，安装 Python 3.12，然后运行 `powershell -File .\install-windows.ps1`。安装脚本创建独立环境，不修改 Codex 配置。详细步骤见上方安装说明。

本 Fork 基于 [krVatsal/illustrator-mcp](https://github.com/krVatsal/illustrator-mcp)，保留原项目说明如下。Windows 用户以以上安装和验收文档为准；macOS 仅完成验收记录中的单轮本地主流程，未覆盖所有原加固版实机项目。

---

# Illustrator MCP Server (Windows & macOS)

Welcome to the **Illustrator MCP Server**! 🎨🚀

This project allows AI agents to **directly create vector graphics** inside **Adobe Illustrator** using natural language prompts.  
It works by sending ExtendScript commands to Illustrator via a local MCP (Model Context Protocol) server.

> Imagine simply describing what you want — like *"draw a small coffee shop during rain"* — and Illustrator brings it to life!

Works on **Windows** (COM automation) and **macOS** (AppleScript/osascript).

---

## ✨ Features
- Control Adobe Illustrator programmatically using AI prompts
- Send ExtendScript (.jsx) scripts directly to Illustrator
- Capture screenshots of the Illustrator window
- Open-source and lightweight
- **Cross-platform:** Windows & macOS
- **Multi-client:** Works with Claude Desktop, Claude Code, Cursor, VS Code Copilot, and JetBrains Copilot

---

## 💻 Installation

### Prerequisites
- **Python 3.12+** — [Download Python](https://www.python.org/downloads/)
- **Adobe Illustrator** installed and running
- **macOS only:** Grant Automation permissions when prompted (System Settings → Privacy & Security → Automation)

### 1. Clone the repository

   ```bash
   git clone --branch codex/local-only https://github.com/scort1213/illustrator-mcp.git
   cd illustrator-mcp
   ```

### 2. Create a virtual environment

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows:**
```bash
python -m venv .venv
.\.venv\Scripts\activate
```

### 3. Install dependencies

```bash
python -m pip install --require-hashes -r requirements.txt
python -m pip install --no-deps .
```
> On macOS, `pywin32` is automatically skipped. No extra macOS packages required.
> Installation is explicit and may download packages. Normal server startup does not install or upgrade packages.
> The second command installs this local project so the client's `-m illustrator` entry point also works when its working directory is outside this checkout. It may download the pinned build tool during this explicit installation step.

### 4. Start the MCP Server (manual / debug mode)

```bash
python -m illustrator
```

### Start an installed environment with one script

```bash
bash run_server.sh
```

This script checks the existing `.venv` and pinned runtime dependencies, then starts the server. If the environment is missing or incompatible, it stops with explicit installation instructions. It never creates an environment, runs `ensurepip`, installs packages or upgrades pip. Launcher messages go to stderr so stdout stays available for MCP.

---

## 🔌 Client Configuration

The server uses **stdio transport** — compatible with all major MCP clients.

The initialization response carries the local-operation policy to the client. Tool discovery and all existing script parameters remain compatible. Reload/restart the client after updating this checkout so it receives the new instructions and tool descriptions.

> **Important:** Do NOT start the server manually when using it through a client. The client starts and manages the server process automatically.

### Claude Desktop

**macOS** — edit `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "illustrator": {
      "command": "/path/to/illustrator-mcp/.venv/bin/python3",
      "args": ["-m", "illustrator"]
    }
  }
}
```

**Windows** — edit `%APPDATA%\Claude\claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "illustrator": {
      "command": "C:\\Users\\<YourUser>\\illustrator-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "illustrator"]
    }
  }
}
```

### Claude Code (CLI)

A `.claude/mcp.json` is included in the repo. Claude Code will auto-detect it. Or add manually:

```bash
claude mcp add illustrator python3 -- -m illustrator
```

### GitHub Copilot (VS Code)

A `.vscode/mcp.json` is included in the repo. VS Code (1.99+) will auto-detect it. Or add to your `settings.json`:

```json
{
  "mcp": {
    "servers": {
      "illustrator": {
        "type": "stdio",
        "command": "python3",
        "args": ["-m", "illustrator"]
      }
    }
  }
}
```
---

## 🎯 Enhanced Prompt System

This MCP server now includes an advanced prompt system to help you create better content! Use these new tools:

- **`get_prompt_suggestions`** - Get categorized prompt examples for different types of content
- **`get_system_prompt`** - Get the optimal system prompt for AI guidance
- **`get_prompting_tips`** - Get tips for creating more effective prompts
- **`get_advanced_template`** - Get structured templates for complex design tasks
- **`help`** - Display comprehensive help and guidance

### 📚 Prompt Categories Available:
- 🎨 Basic Shapes & Geometry
- 📝 Typography & Text  
- 🏢 Logos & Branding
- 🌆 Illustrations & Scenes
- 🎭 Icons & UI Elements
- 🎨 Artistic & Creative
- 📊 Charts & Infographics
- 🏷️ Print & Layout

### 💡 Quick Start with Prompts
Try asking: *"Get me prompt suggestions for logos"* or *"Show me prompting tips"*

For detailed examples and templates, see [PROMPT_EXAMPLES.md](./PROMPT_EXAMPLES.md)

---

## 📋 Sample Prompts I Tried

Here are some prompts I used along with the results it generated:

- **Prompt 1:**  
  *Design a clean, minimal vector art of a small coffee shop during rain, featuring a simple storefront, puddles on the street, and gentle grey clouds in the sky.*

- **Prompt 2:**  
  *Create a watercolor-style illustration of the Mumbai skyline at sunset.*

- **Prompt 3:**  
  *Create a modern, minimalistic logo for a tech startup called 'NeuraTech'.*

*(See attached images for the results!)*

---

## 🍎 macOS Notes

- Adobe Illustrator must be installed and running
- On first use, macOS will ask for **Automation permission** — allow your terminal/IDE to control Illustrator
- If you see "Application not running" errors, open Illustrator first
- Screenshots capture the full screen (Illustrator should be in foreground)

## 🪟 Windows Notes

- Adobe Illustrator must be installed
- The `pywin32` package is required (installed automatically)
- Illustrator scripting must be enabled

---


## 📢 Contributing

Pull requests are welcome!  
Feel free to open issues for feature requests, bugs, or suggestions.
![Stars](https://img.shields.io/github/stars/krVatsal/illustrator-mcp)
![Forks](https://img.shields.io/github/forks/krVatsal/illustrator-mcp)
![License](https://img.shields.io/github/license/krVatsal/illustrator-mcp)

---

Happy creating! 🌈💛
