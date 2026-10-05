# Windows 原生文档预览

当 `view({})` 返回 Illustrator 主页或 `capture_unavailable` 时，可以通过现有 `run` 工具调用 `Document.windowCapture`，取得当前文档窗口的原生 TIFF 预览。它不是整个应用窗口截图，不能用于验收应用菜单、对话框等 UI 状态；不能用它宣称 `view` 的整窗截图已验收通过。

2026-10-05 的新会话对照中，正常启动和 COM 自动启动后的 `view` 均已显示同一专用副本的画布并通过目视核验；随后完整实机回归的 62 个步骤无失败，窗口截图及导出 PNG 也完成了独立目视核验。此前旧会话返回首页的失败记录仍然保留，具体原因尚未确定；本配方继续作为独立的文档内容预览方式，不表示当前 `view` 必然失败。

## 调用方法

1. 在本地准备一个专用输出目录，例如 `D:/audit-work`。保留原稿，使用自己的审核副本。
2. 调用 `get_state({})`，从结果复制已打开副本的完整路径作为 `target_path`。
3. 使用以下 `run` 参数，替换文档路径和输出路径。输出基名不要带扩展名；本机 Illustrator 会添加 `.tiff`。选择尚未使用的基名，避免覆盖以前的证据。

```json
{
  "target_path": "D:/audit-work/review-copy.ai",
  "timeout_seconds": 20,
  "code": "var base = new File('D:/audit-work/review-preview-001'); var output = new File(base.fsName + '.tiff'); if (!base.parent.exists) throw new Error('Output directory does not exist'); if (base.exists || output.exists) throw new Error('Output already exists'); app.activeDocument.windowCapture(base, [800, 600]); if (!output.exists || output.length === 0) throw new Error('Preview output not found'); output.fsName;"
}
```

4. 在本地打开返回的 TIFF 文件，检查预期画板、文本、形状和颜色；如查看器需要 PNG，可在本地进行格式转换。文件存在、图片可解码和脚本成功都不等于视觉验收通过。

此调用不保存或关闭 AI 文档。`run` 原有的目标文档保护、串行执行、超时隔离仍适用；若返回 `outcome_unknown`，先检查状态和输出，不要自动重放。

## 本机实测范围

Windows / Illustrator 28.6.0：专用合成 AI 副本的原生捕获成功生成 800×600 TIFF，已目视查看两个画板、中英文文本、红色矩形及蓝黄矢量图形。在该次旧会话测试中，同一文档的外部 `view` 返回主页。2026-10-05 正常退出旧会话后，新建正常启动会话和新建 COM 自动启动会话的窗口截图均通过；不能据此认定 `/Automation` 有问题，也没有为此修改运行时代码。以上结果未覆盖其他显示器、缩放和 Illustrator 版本。

直接把传入文件命名为 `native-window.tif` 时，本机实际生成 `native-window.tif.tiff`；首次诊断脚本曾因只查找前者而报文件不存在。随后检查已生成的文件完成了视觉核验，没有重新执行捕获。以上配方使用无扩展名基名，另行做了实机核验。

## 再次出现首页异常时

先保存所有需要保留的业务文档，再由用户正常退出并重新打开 Illustrator；不要因截图异常直接结束进程。MCP 不会因该异常自动调用 `Quit`、重启 Illustrator 或重放编辑脚本。本次恢复对照只关闭了经过核验的专用测试副本，没有代替用户关闭业务文档。

重新打开后，应等待实际主窗口出现并就绪，再调用 `get_state({})` 核对文档。实测发现 COM/ROT 可以先于主窗口注册，连接成功不等于窗口已可截图；不能把瞬时未发现窗口误报为启动方式失败。重启是本次已观察到的恢复方式，不是保证所有相同症状都能恢复的根因修复。

2026-10-05 新会话完整实机回归已完成：62 个步骤、0 个失败，`workflow_completed=true`，结束时文档数为 0。自动报告仍保留 `NEEDS_VISUAL_REVIEW`；审核 AI 另行查看 `illustrator-view.jpg` 和 `edited.png` 的实际像素后，独立视觉结论记录为 `PASS`，没有将独立复核结果写成脚本自动判图通过。两张图均正确显示当前主文档的中英文、红色矩形及蓝黄图形；窗口截图中另有旁路文档标签，主文档处于激活状态。

原生 MCP 客户端连接重载仍未验收，stdio 调用通过不能替代该项。以上恢复与回归未修改运行时代码。
