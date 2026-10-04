# Windows 原生文档预览

当 `view({})` 返回 Illustrator 主页或 `capture_unavailable` 时，可以通过现有 `run` 工具调用 `Document.windowCapture`，取得当前文档窗口的原生 TIFF 预览。它不是整个应用窗口截图，不能用于验收应用菜单、对话框等 UI 状态；不能用它宣称 `view` 的整窗截图已验收通过。

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

Windows / Illustrator 28.6.0：专用合成 AI 副本的原生捕获成功生成 800×600 TIFF，已人工查看两个画板、中英文文本、红色矩形及蓝黄矢量图形。同一文档的外部 `view` 仍返回主页。因此，该配方提供已验证的文档内容预览途径，未解决应用整窗显示/捕获异常，也未覆盖其他显示器、缩放和 Illustrator 版本。

直接把传入文件命名为 `native-window.tif` 时，本机实际生成 `native-window.tif.tiff`；首次诊断脚本曾因只查找前者而报文件不存在。随后检查已生成的文件完成了视觉核验，没有重新执行捕获。以上配方使用无扩展名基名，另行做了实机核验。
