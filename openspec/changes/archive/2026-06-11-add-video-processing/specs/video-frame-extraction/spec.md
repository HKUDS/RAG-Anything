# Video Frame Extraction

## Purpose

从视频文件中按采样策略提取关键帧，为 VLM 视觉分析提供代表性画面。支持基于帧率的均匀采样和基于场景变化的智能采样两种策略。

## ADDED Requirements

### Requirement: 视频关键帧提取

系统 SHALL 从视频文件中提取关键帧图像，支持配置采样率和场景变化检测，并将帧保存为临时图片文件供后续 VLM 分析。

#### Scenario: 均匀采样提取帧
- **WHEN** 用户上传一段 60 秒的视频且 `video_sample_rate=1`（1 fps）
- **THEN** 系统提取 60 帧图片
- **THEN** 每帧带有时间戳元数据（秒数）
- **THEN** 帧文件保存为临时 PNG 格式

#### Scenario: 场景变化检测提取帧
- **WHEN** 视频中场景发生变化（相邻帧直方图差异超过阈值 0.3）
- **THEN** 系统在场景切换点额外提取帧
- **THEN** 场景变化帧标记为 `scene_change` 类型

#### Scenario: 帧数上限控制
- **WHEN** 按采样率计算的帧数超过 `max_frames_per_video=60`
- **THEN** 系统从视频中均匀选取最多 60 帧
- **THEN** 优先保留首帧、尾帧和场景变化帧

#### Scenario: 不支持的视频格式
- **WHEN** 视频格式不在支持列表中（非 MP4/AVI/MOV/MKV/WebM）
- **THEN** 系统抛出 `ValueError` 并给出支持的格式列表

#### Scenario: ffmpeg 不可用
- **WHEN** 系统环境中未安装 ffmpeg
- **THEN** 系统抛出 `ImportError` 并提示安装命令

### Requirement: 视频文件验证

系统 SHALL 在处理前验证视频文件的有效性，包括文件存在性、格式支持和基本元数据检查。

#### Scenario: 视频文件存在且有效
- **WHEN** 提供的视频路径指向有效的视频文件
- **THEN** 系统通过 ffprobe 获取视频元数据（时长、分辨率、编码格式）
- **THEN** 验证通过并继续处理

#### Scenario: 视频文件损坏或无法解析
- **WHEN** 视频文件存在但无法被 ffprobe 解析
- **THEN** 系统跳过该视频并记录 `WARNING` 日志
- **THEN** 返回空的帧列表和错误原因

#### Scenario: 视频时长超过限制
- **WHEN** 视频时长超过 `video_max_duration=3600`（默认 1 小时）
- **THEN** 系统记录 `WARNING` 日志
- **THEN** 仅处理前 `video_max_duration` 秒的内容
- **THEN** 在描述中标注"视频已截断"

### Requirement: 视频文件可跳过检测

系统 SHALL 在处理前检查视频是否适合分析，跳过明显无意义的视频（如极短视频、纯色视频）。

#### Scenario: 极短视频
- **WHEN** 视频时长小于 1 秒
- **THEN** 系统跳过 VLM 分析
- **THEN** 使用文件名作为摘要，标记为"短视频片段"

#### Scenario: 静态画面视频
- **WHEN** 所有相邻帧间直方图差异均低于阈值 0.05
- **THEN** 系统仅提取首帧进行分析
- **THEN** 在描述中标注"静态视频"
