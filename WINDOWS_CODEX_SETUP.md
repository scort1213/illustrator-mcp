# Windows 安装与 Codex 接入

实测环境：Illustrator 2024 (28.6.0)、Python 3.12.14。固定依赖：MCP 1.30.0、Pillow 12.3.0、pywin32 312；完整版本及哈希见 requirements.txt。

## 安装

下载 codex/local-only 分支源码 ZIP 并解压，在目录中运行：

```powershell
powershell -File .\install-windows.ps1
```

需已安装 Python 3.12，且 python 指向该版本。可用 -Python 参数指定 Python 路径；-VenvPath 可指定新环境目录。脚本拒绝覆盖已有环境。首次安装需要网络，不包含 Adobe 软件或账号。

安装是明确的单独步骤。日常的 `python -m illustrator` 或 `bash run_server.sh` 不自动安装、更新依赖；`run_server.sh` 遇到环境缺失或版本不符会停止并提示安装入口。修复时在新环境执行安装脚本，再更新客户端的 Python 路径，不要把安装命令写入 MCP 启动配置。

## Codex 配置

配置字段参考 [OpenAI 官方 MCP 文档](https://developers.openai.com/codex/mcp/)。

将路径替换成安装脚本输出的 Python 绝对路径。将以下条目加入 Codex MCP 配置；同名条目存在时更新原条目。

```toml
[mcp_servers.illustrator]
command = 'C:\tools\illustrator-mcp\.venv\Scripts\python.exe'
args = ['-m', 'illustrator']

[mcp_servers.illustrator.env]
PYTHONIOENCODING = 'utf-8'
PYTHONUTF8 = '1'
```

打开 Illustrator，重载 Codex。MCP 由客户端自动启动，无需另开服务终端。先调用 get_state 确认版本与文档；工具出现在清单中不代表 Adobe 已连接。

更新本分支后也须重载客户端，才能收到新的 MCP 初始化指令与 `run` 工具说明。无需新增 MCP 账号或 OAuth 配置。

## 使用与恢复

多文档时 run 必须提供已打开且已保存文档的绝对 target_path。先用合成文档完成编辑、view 预览、保存与重开。窗口最小化时预览会明确拒绝，恢复窗口后再试。

遇到 outcome_unknown 不要重试写入：先 get_state 并核对实际变化，再 recover_connection（acknowledge=true）。恢复连接不撤销已完成修改。

run 执行可信 JSX，不是沙箱。保存前检查输出路径并保留副本。

本地使用指令要求助手不调用 Firefly、生成式 AI、云文档、在线素材或字体激活、浏览器登录及联网命令；遇到本地资源缺失只报告问题，不转用云服务。这些指令保留脚本灵活性，不对任意 JSX 做运行时拦截。Adobe 自身登录、后台联网及 AI 客户端行为不在该指令的控制范围内。

详细范围见 [中文验收记录](ACCEPTANCE_ZH.md) 和 [加固约定](BOUNDARY_HARDENING.md)。
