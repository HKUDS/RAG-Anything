## 1. 数据安全

- [x] 1.1 新建工作流前检测未保存修改 → 弹出确认对话框
- [x] 1.2 加载工作流前检测未保存修改 → 弹出确认对话框
- [x] 1.3 删除工作流 → 确认弹窗（"确定删除 [名称]？"）
- [x] 1.4 添加浏览器 `beforeunload` 事件拦截未保存离开

## 2. 快捷键系统

- [x] 2.1 WorkflowPage 监听键盘：Ctrl+S → 保存、Escape → 关闭面板/关闭对话框
- [x] 2.2 工具栏添加撤销/重做按钮 + Ctrl+Z/Y（通过 ReactFlow undo/redo）

## 3. Handle 交互增强

- [x] 3.1 WorkflowNode handle 增大到 12px + CSS hover 16px + glow boxShadow
- [x] 3.2 连线时 connectionLineStyle 虚线预览

## 4. 面板交互优化

- [x] 4.1 NodeConfigPanel 宽度从 w-72(288px) 缩小到 w-64(256px)
- [x] 4.2 点击画布空白区域关闭面板（onPaneClick → setSelectedNode(null)）
- [x] 4.3 Esc 键关闭面板（统一处理面板+对话框）

## 5. 空状态引导

- [x] 5.1 WorkflowCanvas 在 nodes.length === 0 时显示引导提示（图标+文字）

## 6. 工具栏增强

- [x] 6.1 WorkflowToolbar 显示缩放比例百分比 + 撤销/重做按钮 + 未保存指示点
- [x] 6.2 无节点时隐藏 MiniMap

## 7. 验证

- [x] 7.1 Build 验证 — Vite build 成功 (7.26s)
- [x] 7.2 10 项 UX 改进逐一实现
