# Windows 安装与 Codex 接入

实测环境：Illustrator 2024 (28.6.0)、Python 3.12.14。固定依赖：MCP 1.30.0、Pillow 12.3.0、pywin32 312；完整版本及哈希见 requirements.txt。

## 安装

下载 codex/boundary-hardening 分支源码 ZIP 并解压，在目录中运行：

```powershell
powershell -File .\install-windows.ps1
```

需已安装 Python 3.12，且 python 指向该版本。可用 -Python 参数指定 Python 路径；-VenvPath 可指定新环境目录。脚本拒绝覆盖已有环境。首次安装需要网络，不包含 Adobe 软件或账号。

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

## 使用与恢复

多文档时 run 必须提供已打开且已保存文档的绝对 target_path。先用合成文档完成编辑、view 预览、保存与重开。窗口最小化时预览会明确拒绝，恢复窗口后再试。

遇到 outcome_unknown 不要重试写入：先 get_state 并核对实际变化，再 recover_connection（acknowledge=true）。恢复连接不撤销已完成修改。

run 执行可信 JSX，不是沙箱。保存前检查输出路径并保留副本。

详细范围见 [中文验收记录](ACCEPTANCE_ZH.md) 和 [加固约定](BOUNDARY_HARDENING.md)。
