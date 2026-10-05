# Windows 独立审核版

分支：`codex/windows-audit-20261004`。基线：`f6d60da2f50fa4eaedc39d61bb0ea3f7a216fa71`。
2026-10-04 核对时，GitHub 只列出 main，该提交包含旧 boundary-hardening 的历史和之后两次本地执行加固。已有两份 Windows 本地副本分别停在 `01f1e0d`、`983845e`，没有用于冒充最新源码。

**2026-10-05 当前结果：**旧会话实际停留在首页的问题，在正常退出后新建的正常启动会话和 COM 自动启动会话中均未复现；两种新会话的同副本文档画布截图已通过目视核验。随后完整实机回归的 62 个步骤无失败，窗口截图和导出 PNG 的独立视觉结论为 `PASS`，结束时文档数为 0。具体根因未定，运行时代码保持不变。原生 MCP 客户端重载仍未验收；下文历史失败记录不代表当前新会话仍然失败。

## 本次修复

- 同一个 Windows 目录可以有长路径、8.3 短路径、尾点等表示。旧版本以路径字面量命名 mutex，可能让两个客户端同时进入。现在规范化真实目录后生成互斥名称；回归使用真实 Windows 两进程互斥。
- 脚本归属文件为 `null`、数组或超大 PID 时，恢复过程可能崩溃。现在保留这些无法证明归属的目录，并继续检查其余目录。
- Windows `target_path` 拒绝缺盘符/共享根的路径，避免把根相对路径误当成完整目标。
- Windows 窗口捕获对已复现的近乎全灰、未渲染画面返回明确错误，不再把可解码空图当作有效预览；保留不回退到桌面的约束。刻意大面积深灰设计也可能被保守拒绝，其他捕获缺陷仍需视觉核验。
- Node 状态脚本测试显式按 UTF-8 解码，避免中文 Windows 默认 GBK 导致误失败。
- 禁联网握手测试先建立 Windows 事件循环的内部回环通道，然后才审计服务器启动与工具调用。服务器工作仍不得尝试网络连接。
- 远端 Windows CI 使用 8.3 临时目录名，暴露三个测试夹具的路径字面比较问题。链接夹具改按文件身份匹配并确认确实命中；默认目录断言对两端统一规范化。本机真实短路径复现修前失败，修后长、短路径均通过，没有放宽产品路径检查。
- 子进程截止时间传递测试使用固定时钟并严格断言剩余预算，消除 Windows CI 浮点计时舍入导致的偶发误失败。

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
- 两份用户原稿的专用副本完成编辑、保存重开，原稿前后 SHA256 一致。其中一份日历副本原有文字框数（263）和字符总数（2166）保持一致，未逐字比较全部原文；新增独立测试文字框持久化，PNG 导出已目视确认内容。另一份轮廓素材只验证结构保存，其首画板不能代表画板外全部画面。
- **窗口截图历史异常与当前恢复状态**：早期近乎全灰图通过了解码，但目视复核不含文档；本版已验证会对此返回 isError / capture_unavailable。后续旧会话又出现实际停留在首页的异常，app.redraw、激活窗口和 PrintWindow 不同参数均未解决。2026-10-05 正常退出旧会话后，正常启动和 COM 自动启动的新会话均通过同副本文档画布截图目视核验，详见末节。根因尚未确定，仍不能用自动化“返回图片”代替视觉验收；明确目标 PNG 导出和原生文档预览是独立的已验证途径。
- **SVG 导出限制**：本机默认字体选项导出曾挂起；超时隔离生效，仅读取恢复也无法完成后，定向停止了本任务启动且只打开合成文档的无响应 Illustrator。显式 SVGFontType.OUTLINEFONT 导出通过，但会改变当前文档的 SVG/文字轮廓状态；应先保存原生 AI，导出后关闭 SVG 并重开 AI，不能直接在 SVG 状态继续文字审核。没有宣称所有 SVG 字体选项均可用。
- 未验收：当前 Codex 会话原生工具重载、两个真实 MCP 客户端并发调用 Adobe、长时间压力测试、其他 Illustrator/DPI/显示器组合、macOS 实机。Windows 单元和 CI 不替代这些验收。

上述核心编辑/恢复结果可供审核和美工复用；本分支保留历史截图异常和新会话恢复的证据，仍需按实际文档进行视觉复核，不是全部 Windows 图形场景认证。原有 main/Mac 历史不被覆盖。

源码与文档可上传仓库；私人原稿、副本、应用截图、机器路径和原始日志只保存在本地证据目录。

## 2026-10-04 UTC 有界补测

本轮没有更改运行时代码，没有重复上一轮全部业务验收，也没有修改系统权限、全局 MCP 配置或结束 Illustrator 进程。

**截图：尚未通过文档画面验收。** 新启动的 COM 实例先能处理文档，但 UI 尚未出现；窗口就绪后确认位于同一交互会话的 WinSta0/Default。现有 `view` 可以返回首页图像，但不含已打开的合成文档。对同 PID 可见子窗口做了最多两个直接捕获，均为首页容器；单独调用受支持的 `Document.activate()`、重绘并等待脚本返回后，状态仍正确报告一份文档、一个视图，图像仍是首页。没有把“有图像返回”登记为文档预览通过。灰屏检测只覆盖已知灰屏，不能证明其他返回图像一定显示目标文档。

Adobe 官方说明可点击首页左上 Illustrator 图标旁的返回箭头回到当前文档；Windows 默认 `Ctrl+E` 切换该文档的 GPU/CPU 预览。SVG 现场恢复后，本轮确认前台窗口和视口与已观察图像一致，对返回箭头位置只点击一次，捕获仍是首页，未证实界面切换。没有确认当前画布预览模式，因此未盲发快捷键、未修改全局 GPU 首选项。需要后续在真实可见画布上确认模式后才能做 CPU 对照；本轮停止继续试探。参考：[切换首页与工作区](https://helpx.adobe.com/illustrator/desktop/get-started/learn-the-basics/switch-between-the-workspace-and-homescreen.html)、[Adobe 快捷键表](https://helpx.adobe.com/illustrator/using/default-keyboard-shortcuts.html)。

**SVG：取得保留文字的可用参数，完整字形导出超时后仍在后台完成。** 本机新建 `ExportOptionsSVG` 实际读数为 `SVGFONT + ALLGLYPHS`，嵌入位图和保留可编辑性均为 false；不能以参考文档的默认值替代本机读数。两个测试副本字节相同，均使用原有 MicrosoftYaHei 文字，导出时显式设置 `SVGFONT` 和嵌入位图，仅改变字体子集：

| 字体子集 | 本轮结果 |
| --- | --- |
| `GLYPHSUSED` | 单独导出 0.250 秒；13,273 字节，XML 可解析，含 1 个 text、1 个 font、25 个 glyph、1 个 image；自己的副本已关闭。 |
| `ALLGLYPHS` | 30.015 秒返回 `outcome_unknown`；随后仅一次状态读取在 30.016 秒返回 `queue_timeout`，未派发到 Adobe。初次文件检查为 0 字节；整理时发现后台已完成 26,935,538 字节的有效 SVG，含 29,693 个 glyph。原生 AI 副本哈希未变。未测得精确导出总耗时。 |

该单变量对照说明本机完整字形导出会超过此次 30 秒预算并产生大文件，本次不是永久挂起，没有证据认定 MCP 转发代码有错。两个 SVG 都能解析，文字元素内容与预期合成文字一致；只验证了文件生成、文字内容和 XML 结构，本轮没有重开或渲染 SVG，不把这些检查当作视觉一致性验收。已通过的 PNG 导出和上一轮 OUTLINE 路径仍是独立事实。

在已明确选定、已保存的专用副本中，可复用以下经过本轮文件级验证的导出选项：

```javascript
var options = new ExportOptionsSVG();
options.fontType = SVGFontType.SVGFONT;
options.fontSubsetting = SVGFontSubsetting.GLYPHSUSED;
options.embedRasterImages = true;
app.activeDocument.exportFile(new File("D:/audit-work/text-subset.svg"), ExportType.SVG, options);
```

本轮成功 SVG 导出后，当前文档路径变为 SVG。导出前先保存原生 AI；结束后按实际状态关闭自己的 SVG 并重开 AI，不能在未核对的导出后状态继续审核文字。

**恢复和最终状态。** 超时后没有重放导出或结束进程。发现文件已完整生成这一新证据后，才重新读取状态，确认只有自己的 `allglyphs.svg` 且已保存，显式调用 `recover_connection`，再关闭自己的文档。随后的一次首页返回对照也只操作专用副本并关闭；最终真实状态为零文档。无需用户再处理此次 SVG 隔离现场。已核验的临时副本可以清理，保留精简证据和小字形子集 SVG。

**原生客户端接入仍需客户端操作。** 已安装解释器和 stdio 接口已验证，当前会话尚未验证原生 MCP 重载。将本文前面的独立服务器配置加入审核项目或客户端 MCP 设置，然后重载该连接；服务器/连接列表出现 `illustrator_windows_audit`，且其工具包含 `get_state` 后，先调用 `get_state({})`。不自动替换其他项目服务器或改写全局配置。

## 旧会话窗口问题定位与可用的原生预览

在此前旧会话中，进一步对照仍未通过应用窗口截图验收，但找到了可用的文档预览方式：现有 `run` 工具调用 `Document.windowCapture`。实机生成的 800×600 TIFF 已目视确认包含两个画板、中英文文本和预期矢量图形；同次测试的外部 `view` 为主页。[完整调用配方](WINDOWS_DOCUMENT_PREVIEW.md)。该原生预览是独立能力，不替代应用整窗截图验收；新会话的截图结果见下一节。

定位证据如下：

- GDI 和 Windows Graphics Capture 对同一已核对 PID/HWND 的 Illustrator 窗口均得到主页。WGC 只传入精确窗口句柄，未使用桌面/显示器回退；诊断依赖已清理，未加入产品依赖。
- 对照 `DONTDISPLAYALERTS` 与开文档前临时 `DISPLAYALERTS`，结果相同；脚本结束后的实际全局交互级别为 `DISPLAYALERTS`，已恢复。不能把 guard 内读到的临时值当作全局配置。
- 打开文档后 COM `HomeScreenVisible` 为 false，文档数为 1；同一进程只有一个可见顶层窗口，标题正确包含专用副本文件名。没有发现被窗口类筛选遗漏的另一个可见文档窗。
- 从正常文件打开入口调用 Illustrator，也得到相同结果。输入桌面为 `Default`。该对照复用了现有进程，不证明 `/Automation` 启动模式无关。
- 文档报告 `DefaultPreview` / `NormalScreenMode` / `GPU Preview`；原生文档窗口捕获成功。未切换 GPU 设置、修改工作区或重置偏好。

旧会话异常表现为主窗口显示或外部捕获结果与文档状态不一致；文档内容读取、编辑和原生渲染有成功证据。现有证据不足以判定具体为 Adobe 工作区状态、Windows 合成兼容性或 GPU 驱动问题，不应直接归因，也不应通过扩大截图范围掩盖问题。没有为未经证实的原因修改运行时代码或 Mac 实现。

验收脚本另修正了一个可确认的问题：JPEG 可解码只表示图像传输成功。自动业务检查完成且无其他失败时，脚本现在返回 `NEEDS_VISUAL_REVIEW` 和退出码 2；发生失败仍返回 `FAIL` 和退出码 1。必须另行检查保存的图像，不能把自动脚本成功当作文档画面正确。

## 2026-10-05 UTC 新会话恢复对照

**旧会话问题发生在实际显示状态，不能仅归为截图错误。** 用户提供的同期屏幕图像显示 Illustrator 实际处于首页；同一专用副本在 COM 中已打开，`HomeScreenVisible` 为 false。该证据确认了真实界面与文档状态的差异，但没有确定其底层原因。

核验并关闭唯一专用测试副本后，正常退出旧进程，再对同一副本进行以下对照，没有修改工作区、GPU 首选项或运行时代码：

| 新会话启动方式 | 已验证结果 |
| --- | --- |
| 无参数正常启动 Illustrator | 主窗口就绪后打开同一副本，`view` 显示文档画布，目视核验通过。 |
| 新建 COM 自动启动会话，命令行含 `/Automation -Embedding` | 同样等待主窗口就绪后打开同一副本，`view` 显示文档画布，目视核验通过。 |

初次正常启动时，ROT 已经注册而主窗口尚未出现，诊断脚本的一次即时窗口断言因此停止；随后窗口正常出现。后续对照等待实际窗口就绪，不把 COM 连接成功直接当作 UI 就绪，也不把该次断言失败当成正常启动失败。

两种新会话均通过，因此没有证据把 `/Automation` 或 COM 自动启动本身认定为根因。当前结论是旧会话异常在正常退出并新建会话后恢复；重启同时改变了会话状态，不能据此断言具体组件已被修复。产品保留自动启动能力，不因截图异常自动调用 `Quit` 或重启 Illustrator，Mac 实现不变。`Document.windowCapture` 仍是独立可用的文档内容预览能力。

如用户再次遇到相同症状，应先保存所有需要保留的业务文档，再由用户正常退出并重开 Illustrator，等待实际主窗口就绪后调用 `get_state({})` 并复核目标文档。不自动结束进程、不自动重放原编辑；重启也不能替代 `outcome_unknown` 后的结果核对与显式恢复。

**本次完整实机回归：**本地 `evidence/acceptance-session-recovered/report.json` 记录 62 个步骤、0 个失败，`workflow_completed=true`、`final_document_count=0`。自动报告仍为 `NEEDS_VISUAL_REVIEW`，没有修改成自动视觉通过。随后独立目视核验 `illustrator-view.jpg` 与 `edited.png`，两张图均正确显示当前主文档的中英文、红色矩形及蓝黄图形；窗口截图包含旁路文档和主文档两个标签，主文档处于激活状态。该次独立视觉结论另记为 `PASS`。

本次结果补齐了新会话中的窗口图像视觉验收，不覆盖其他 Illustrator/DPI/显示器组合，也不证明旧会话根因已修复。原生 MCP 客户端连接重载仍未验收，既有 stdio 验证不等同于客户端已重载。
