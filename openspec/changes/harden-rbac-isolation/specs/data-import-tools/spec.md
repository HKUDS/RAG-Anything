# Data Import Tools (Delta)

## MODIFIED Requirements

### Requirement: 文件夹导入路径白名单
`POST /upload/folder` 的 `folder_path` SHALL 经过 `realpath` 归一化后位于白名单根目录之内（`FOLDER_UPLOAD_ROOTS`，默认 `uploads/` 与 `WORKING_DIR`），越界返回 403。

#### Scenario: 白名单内路径
- **WHEN** `folder_path` 位于配置的白名单根目录内
- **THEN** 导入 SHALL 正常进行

#### Scenario: 越界路径
- **WHEN** `folder_path` 解析后位于白名单根目录之外（如系统目录或任意盘符路径）
- **THEN** 服务端 SHALL 返回 403，且不读取任何文件
