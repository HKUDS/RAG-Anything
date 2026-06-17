# Video Frame Cache

## Purpose

基于视频文件路径、修改时间和采样率缓存帧级 VLM 描述结果，避免同一视频重复处理时重复调用 VLM，节约 API 成本。

## ADDED Requirements

### Requirement: 帧描述缓存

系统 SHALL 在 `VideoModalProcessor` 实例上维护帧描述缓存，以 `video_path + mtime + sample_rate` 的哈希为键，缓存帧描述列表。

#### Scenario: 首次处理缓存未命中
- **WHEN** 视频文件首次被处理
- **THEN** 缓存查找失败（缓存键不存在）
- **THEN** 系统正常执行帧提取和 VLM 分析
- **THEN** 分析完成后帧描述存入缓存

#### Scenario: 重复处理缓存命中
- **WHEN** 同一视频文件（路径相同、mtime 未变、sample_rate 相同）再次被处理
- **THEN** 缓存查找命中
- **THEN** 系统跳过帧提取和 VLM 分析
- **THEN** 直接使用缓存的帧描述生成综合描述

#### Scenario: 文件修改后缓存失效
- **WHEN** 视频文件的 mtime 发生变化（文件被修改或替换）
- **THEN** 缓存键不匹配
- **THEN** 系统重新执行完整的帧提取和 VLM 分析
- **THEN** 新结果覆盖旧缓存

#### Scenario: 采样率变化后缓存失效
- **WHEN** 同一视频使用不同的 `video_sample_rate` 处理
- **THEN** 缓存键不匹配
- **THEN** 系统使用新采样率重新提取帧和分析

### Requirement: 缓存开关控制

系统 SHALL 通过 `ENABLE_FRAME_CACHE` 环境变量控制帧缓存功能的启用/禁用，默认启用。

#### Scenario: 缓存启用（默认）
- **WHEN** 未设置 `ENABLE_FRAME_CACHE` 或设置为 `true`
- **THEN** `VideoModalProcessor` 启用帧缓存
- **THEN** 每次帧分析前检查缓存

#### Scenario: 缓存禁用
- **WHEN** 设置 `ENABLE_FRAME_CACHE=false`
- **THEN** `VideoModalProcessor` 不检查也不写入缓存
- **THEN** 每次处理都重新执行帧提取和 VLM 分析
