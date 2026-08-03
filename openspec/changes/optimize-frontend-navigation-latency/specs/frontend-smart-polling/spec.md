# Spec: 前端智能轮询

## MODIFIED Requirements

### Requirement: 页面可见性检测
前端轮询页面（看板与知识库详情页）SHALL 根据浏览器页面可见性状态控制数据轮询；页面隐藏时 SHALL 停止轮询，恢复可见时 SHALL 立即执行一次刷新。

#### Scenario: 页面隐藏时停止
- **WHEN** 用户切换到其他浏览器标签页
- **THEN** 看板与知识库详情页 SHALL 停止数据轮询

#### Scenario: 页面恢复时立即刷新
- **WHEN** 用户切回轮询页面标签页
- **THEN** 页面 SHALL 立即执行一次数据刷新

### Requirement: 任务感知轮询间隔
知识库详情页轮询间隔 SHALL 根据上传任务状态动态调整：存在非终态上传任务时 SHALL 以 15 秒间隔轮询核心数据，无活动任务时 SHALL 停止核心数据轮询；任务全部转为终态的当次检查 SHALL 执行最后一次核心数据刷新；图谱数据 SHALL 仅在图谱标签页激活时刷新。

#### Scenario: 存在处理中的上传任务
- **WHEN** 知识库存在 queued/processing/handling 状态的上传任务
- **THEN** 详情页 SHALL 以 15 秒间隔轮询文档与统计数据

#### Scenario: 无活动上传任务
- **WHEN** 知识库无非终态上传任务
- **THEN** 详情页 SHALL 停止核心数据的定时轮询

#### Scenario: 任务转为终态时最终刷新
- **WHEN** 最近一次检查发现上传任务全部转为终态
- **THEN** 详情页 SHALL 立即执行一次文档与统计刷新，然后停止定时轮询

#### Scenario: 图谱标签页未激活
- **WHEN** 用户停留在文档标签页
- **THEN** 图谱与实体数据 SHALL 不被定时刷新
