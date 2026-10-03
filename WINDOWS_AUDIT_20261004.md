# Windows 独立审核版

分支：`codex/windows-audit-20261004`。基线：`f6d60da2f50fa4eaedc39d61bb0ea3f7a216fa71`。
2026-10-04 核对时，GitHub 只列出 main，该提交包含旧 boundary-hardening 的历史和之后两次本地执行加固。已有两份 Windows 本地副本分别停在 `01f1e0d`、`983845e`，没有用于冒充最新源码。

## 本次修复

- 同一个 Windows 目录可以有长路径、8.3 短路径、尾点等表示。旧版本以路径字面量命名 mutex，可能让两个客户端同时进入。现在规范化真实目录后生成互斥名称；回归使用真实 Windows 两进程互斥。
- 脚本归属文件为 `null`、数组或超大 PID 时，恢复过程可能崩溃。现在保留这些无法证明归属的目录，并继续检查其余目录。
- Windows `target_path` 拒绝缺盘符/共享根的路径，避免把根相对路径误当成完整目标。
- Windows 窗口捕获对已复现的近乎全灰、未渲染画面返回明确错误，不再把可解码空图当作有效预览；保留不回退到桌面的约束。刻意大面积深灰设计也可能被保守拒绝，其他捕获缺陷仍需视觉核验。
- Node 状态脚本测试显式按 UTF-8 解码，避免中文 Windows 默认 GBK 导致误失败。
- 禁联网握手测试先建立 Windows 事件循环的内部回环通道，然后才审计服务器启动与工具调用。服务器工作仍不得尝试网络连接。
- 远端 Windows CI 使用 8.3 临时目录名，暴露三个测试夹具的路径字面比较问题。链接夹具改按文件身份匹配并确认确实命中；默认目录断言对两端统一规范化。本机真实短路径复现修前失败，修后长、短路径均通过，没有放宽产品路径检查。

原有任意可信 JSX 能力、九个工具及本地操作指令保留。没有给 JSX 增加脚本沙箱。

## 审核项目调用

按 [Windows 安装说明](WINDOWS_CODEX_SETUP.md) 在独立目录安装。部署应固定到实际验收的提交，不要仅依赖可移动的分支名。安装不会改写现有 MCP 配置。

可为审核项目增加独立服务器名，避免覆盖其他项目的连接：

```toml
[mcp_servers.illustrator_windows_audit]
command = 'C:\tools\illustrator-mcp-windows\.venv\Scripts\python.exe'
args = ['-m', 'illustrator']

[mcp_servers.illustrator_windows_audit.env]
PYTHONIOENCODING = 'utf-8'
PYTHONUTF8 = '1'
```

重载后先调用 `get_state({})`。核对 Illustrator 版本和打开文档路径后再操作。脚本示例只读取指定副本的原生文字框数量：

```json
{
  "code": "String(app.activeDocument.textFrames.length)",
  "target_path": "C:\\audit-work\\document-copy.ai",
  "timeout_seconds": 30
}
```

把该参数传给 `run`。需要读取文案、位置、图层或 UUID 时，在可信 JSX 中逐项提取；保存/修订只能指向专用副本。`get_state` 是结构快照，不是完整文字审核，也不检查链接文件是否存在。图片中的文字、轮廓化文字与语义审核需要另外处理，不能把原生文字框计数当成全部内容已经审核。

`outcome_unknown` 表示脚本可能已经部分或全部执行。先用 `get_state` 并核对具体编辑结果，再调用 `recover_connection({"acknowledge":true})`；不能直接重放原写入。

所有控制同一个 Illustrator 的客户端须使用同一版本和同一本地安全目录。升级前结束旧操作并统一重载；不同安全根、旧客户端、人工编辑不参与本版互斥。

## 复验入口

自动回归不会编辑 Adobe 文档：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

实机验收脚本单独运行，先关闭业务文档，指定一个新的空测试目录；它通过真实 MCP stdio 控制 Illustrator，并保留步骤报告与生成的测试产物。完整命令与本机结果在本文件验收结果中记录。

```powershell
.\.venv\Scripts\python.exe scripts\windows_acceptance.py `
  --server-python .\.venv\Scripts\python.exe `
  --workspace D:\acceptance\new-run
```

脚本要求工作区不存在、父目录已经存在。默认把窗口截图错误也计为整体验收失败，不能用它的核心编辑通过结果推断全部功能通过。

## 本机实测结果与限制

Windows、Illustrator 28.6.0、Python 3.12.14、MCP 1.30.0、Pillow 12.3.0、pywin32 312。

- 自动回归 79 项：71 通过、8 项 POSIX/非 Windows 路径专属测试跳过。包括真实 Windows 两进程互斥、真实 stdio 握手，其余 Adobe 对象测试使用模拟对象；不冒充实机验收。
- 独立环境锁定安装和 pip check 通过。从仓库目录外运行已安装包，核对关键源码哈希、9 工具发现、5 提示工具和实际 Illustrator 状态读取。
- 合成文档实机通过：双文档明确目标、多画板、分组、原生中英文文字和颜色编辑、链接图片元数据、保存关闭重开、PNG 导出像素检查、SVG 轮廓导出后重开原生 AI 仍可编辑。旁路文档的内存状态及磁盘 SHA256 均保持不变。
- 不存在/不明确目标拒绝；实际执行中的超时返回 outcome_unknown，后续写入被阻止；读取状态确认部分操作只执行一次后显式恢复，未重放写入。
- 两份用户原稿的专用副本完成编辑、保存重开，原稿前后 SHA256 一致。其中一份日历副本原有 263 个原生文字框、2166 个字符保持一致，新增独立测试文字框持久化；PNG 导出已目视确认内容。另一份轮廓素材只验证结构保存，其首画板不能代表画板外全部画面。
- **窗口截图仍有本机限制**：返回的近乎全灰图通过了解码，但目视复核不含文档。app.redraw、激活窗口和 PrintWindow 不同参数均未解决。本版已验证会对此返回 isError / capture_unavailable。窗口画面可用性没有通过，不能用自动化“返回图片”代替视觉验收。审核预览请使用已验证的明确目标 PNG 导出。
- **SVG 导出限制**：本机默认字体选项导出曾挂起；超时隔离生效，仅读取恢复也无法完成后，定向停止了本任务启动且只打开合成文档的无响应 Illustrator。显式 SVGFontType.OUTLINEFONT 导出通过，但会改变当前文档的 SVG/文字轮廓状态；应先保存原生 AI，导出后关闭 SVG 并重开 AI，不能直接在 SVG 状态继续文字审核。没有宣称所有 SVG 字体选项均可用。
- 未验收：当前 Codex 会话原生工具重载、两个真实 MCP 客户端并发调用 Adobe、长时间压力测试、其他 Illustrator/DPI/显示器组合、macOS 实机。Windows 单元和 CI 不替代这些验收。

上述核心编辑/恢复结果可供审核和美工复用；本分支是带已知截图限制的 Windows 审核交付，不是全部 Windows 图形场景认证。原有 main/Mac 历史不被覆盖。

源码与文档可上传仓库；私人原稿、副本、应用截图、机器路径和原始日志只保存在本地证据目录。
