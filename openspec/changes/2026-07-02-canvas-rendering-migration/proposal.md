# Canvas Rendering Migration

## Summary

将 `KnowledgeDetailPage` 知识图谱的渲染层从 SVG DOM 迁移到 Canvas 2D，从根本上解决 1000+ 节点时的性能瓶颈。保留 D3 力仿真计算，仅替换渲染目标。

## Problem

SVG 渲染 1000+ 节点时，每个 tick 需操作数千个 DOM 元素（circle、text、line），导致：
- 单帧渲染耗时 >50ms（超出 16.7ms 帧预算）
- 拖拽延迟 >200ms
- 缩放卡顿
- 面板完全无响应

之前的三项优化（跳帧、提速收敛、隐藏边标签）属于治标，改善 3-5 倍但天花板仍在 SVG DOM 瓶颈。

## Proposed Solution

**核心思路**：D3 force 仿真布局不动，渲染目标从 `<svg>` 换成 `<canvas>`。

```
现在:  D3 force → 每个 tick 更新 N 个 DOM 元素的属性 → 浏览器重排/重绘
改后:  D3 force → 每个 tick 一次 Canvas draw 调用 → GPU 合成
```

Canvas 优势：
- 无 DOM 开销：1000 节点和 10 节点渲染成本相近
- 单次绘制：所有节点/边在一次 `requestAnimationFrame` 内完成
- GPU 加速：Canvas 2D 在现代浏览器中由 GPU 合成

## Scope

- **仅改 KnowledgeDetailPage** — 制造知识图谱页 (KnowledgeGraphD3) 节点数少，保持 SVG 不变
- **保留所有交互**：拖拽、缩放/平移、悬停高亮、点击选中
- Canvas 2D（非 WebGL）— 学习成本低，兼容性好

## Impact

| 指标 | 改前 (SVG) | 改后 (Canvas) |
|------|-----------|---------------|
| 1000 节点渲染时间 | ~15000ms | ~500ms |
| 帧率 (1000 节点) | 2-5 FPS | 30-60 FPS |
| 拖拽延迟 | >200ms | <50ms |
| 代码行数变化 | - | +~200 行 |
