## 1. 配置扩展

- [x] 1.1 在 `RAGAnythingConfig` 中添加 `video_frame_concurrent`（默认 3）和 `enable_frame_cache`（默认 true）
- [x] 1.2 更新 `env.example` 添加 `VIDEO_FRAME_CONCURRENT` 和 `ENABLE_FRAME_CACHE` 说明

## 2. 帧缓存实现

- [x] 2.1 在 `VideoModalProcessor.__init__()` 中添加 `_frame_cache: dict` 和 `_enable_frame_cache: bool`
- [x] 2.2 实现 `_get_cache_key(video_path, sample_rate) -> str` 方法（基于 path + mtime + sample_rate 哈希）
- [x] 2.3 在 `generate_description_only()` 中集成缓存：处理前查缓存，处理后写缓存

## 3. 帧分析并行化

- [x] 3.1 在 `VideoModalProcessor.__init__()` 中添加 `_frame_semaphore: asyncio.Semaphore`（值来自 `video_frame_concurrent` 配置）
- [x] 3.2 重构 `generate_description_only()` 中的帧分析循环：创建 `analyze_frame()` 内部 async 函数，使用 `asyncio.gather` 并发执行
- [x] 3.3 每帧失败时返回错误描述字符串而非抛异常，确保 `gather` 不会因单帧失败而全部取消

## 4. 集成

- [x] 4.1 在 `raganything.py` 的 `_initialize_processors()` 中传入 `video_frame_concurrent` 和 `enable_frame_cache` 配置给 `VideoModalProcessor`
- [x] 4.2 在 `raganything.py` 的 `VideoModalProcessor` 构造中传入上述参数

## 5. 测试

- [x] 5.1 编写帧缓存单元测试（命中、未命中、mtime 变化失效、采样率变化失效、缓存禁用）
- [x] 5.2 编写并发帧分析单元测试（正常并发、部分失败、串行回退、排序正确性）
- [x] 5.3 集成测试：同一视频两次处理，第二次使用缓存（VLM 调用次数验证）
