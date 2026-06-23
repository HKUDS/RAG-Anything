# Video Frame Extraction (Delta)

## ADDED Requirements

### Requirement: 帧提取时长感知路由

系统 SHALL 根据视频时长选择最优帧提取策略：短视频使用单次 ffmpeg fps filter（减少子进程开销），长视频使用串行 seek（避免decode浪费）。

#### Scenario: 短视频使用fps filter
- **WHEN** 视频时长 < 180秒 且 源帧数/输出帧数 < 100
- **THEN** 系统使用单次 ffmpeg `fps` filter 提取所有帧
- **THEN** 帧时间戳通过 `index / sample_rate` 计算
- **THEN** 帧文件命名为 `frame_0001.png`, `frame_0002.png` ...

#### Scenario: 长视频使用串行seek
- **WHEN** 视频时长 ≥ 180秒 或 源帧数/输出帧数 ≥ 100
- **THEN** 系统使用多次 `ffmpeg -ss` seek 逐帧提取
- **THEN** 帧时间戳由 seek 位置确定

#### Scenario: fps filter失败时回退
- **WHEN** fps filter 调用失败（如精简ffmpeg构建不含libavfilter）
- **THEN** 系统回退到串行 seek 模式
- **THEN** 记录 `WARNING` 日志"fps filter failed, falling back to per-frame seek"

## MODIFIED Requirements

### Requirement: 视频帧数上限控制

系统 SHALL 对视频提取帧数实施上限控制，同时强制执行视频时长上限。当视频时长超过配置限制时，拒绝处理而非截断。

#### Scenario: 帧数在限制内
- **WHEN** 按采样率计算的帧数 ≤ `video_max_frames`（默认60）
- **THEN** 系统提取所有计算帧
- **THEN** 优先保留首帧、尾帧和场景变化帧（均匀分布）

#### Scenario: 帧数超过上限
- **WHEN** 采样率计算的帧数 > `video_max_frames`
- **THEN** 系统均匀选取最多 `video_max_frames` 帧
- **THEN** 减少帧数而非截断视频时长

#### Scenario: 视频时长超过上限
- **WHEN** 视频时长 > `video_max_duration`（默认3600秒）
- **THEN** 系统在 `generate_description_only` 入口处拒绝处理
- **THEN** 抛出 `ValueError` 包含具体时长和上限值
- **THEN** 不进行帧提取、转录或VLM分析
- **THEN** 调用方捕获异常后跳过该视频或创建 fallback entity

### Requirement: 视频文件可跳过检测

系统 SHALL 在处理前检查视频是否适合分析，跳过明显无意义的视频（如极短视频、超长视频）。

#### Scenario: 极短视频
- **WHEN** 视频时长小于 1 秒
- **THEN** 系统跳过 VLM 分析
- **THEN** 使用文件名作为摘要，标记为"短视频片段"

#### Scenario: 超长视频
- **WHEN** 视频时长超过 `video_max_duration` 配置值
- **THEN** 系统拒绝处理
- **THEN** 抛出 `ValueError` 并记录 `WARNING` 日志包含视频时长和限制值
- **THEN** 调用方收到明确错误信息而非被静默截断
