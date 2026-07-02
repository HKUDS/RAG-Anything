# Design: 制造智能体 KB 选择器

## Context

制造智能体 QA/诊断端点硬编码使用 `create_rag()` 默认 KB。需要支持前端选择 KB。

## Decision

**选择**: 制造 API 端点接受 `?kb=` 参数，后端按 KB 名动态创建或缓存 RAG 实例。

**理由**: 复用已有 `create_rag(working_dir=...)` 工厂，每个 KB 独立 RAG 实例，缓存避免重复创建。

## Goals / Non-Goals

**Goals**: 制造智能体能检索任意 KB 的内容
**Non-Goals**: 不修改全局 KB 切换逻辑
