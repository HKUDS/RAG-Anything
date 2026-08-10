## ADDED Requirements

### Requirement: Personal settings collapse per-file-type parser overrides
The upload/parsing section SHALL show the global parser selector labeled “默认解析器” together with a hint that all file types use this parser unless individually overridden and that uninstalled parsers are disabled. The per-file-type selectors (`pdf`, `office`, `image`) SHALL be collapsed inside an expandable section labeled “按文件类型指定（可选）” that follows the global parser and video group; the collapsed summary SHALL show “全部跟随默认” when no override is set, otherwise “已指定：” followed by the Chinese labels of the overridden types. The summary SHALL reflect the current draft (unsaved changes) falling back to effective values, SHALL iterate types in the canonical order `pdf`, `office`, `image`, and SHALL ignore empty values and unknown keys. Expanding the section SHALL reveal the per-type selectors with their existing row ids, option filtering, uninstalled-disable, and draft semantics unchanged, and the video row SHALL remain outside the expandable section next to the global parser row.

#### Scenario: Parser section shows only the global row by default
- **WHEN** a user opens the upload/parsing section with no per-type overrides saved
- **THEN** the section shows the “默认解析器” row with the explanatory hint, the expandable “按文件类型指定（可选）” section with summary “全部跟随默认”, and the per-type selectors are hidden until expanded

#### Scenario: Collapsed summary lists overridden types
- **WHEN** a user has saved overrides for PDF and office and reopens the section
- **THEN** the collapsed summary shows “已指定：PDF、办公文档” while the expanded rows retain the saved values

#### Scenario: Video row stays outside the expandable section
- **WHEN** a user opens the upload/parsing section
- **THEN** the “启用视频处理” row appears next to the global parser row and not inside the per-type expandable section

#### Scenario: Summary updates from draft before save
- **WHEN** a user changes the office row to a parser without saving and the section is collapsed
- **THEN** the summary shows “已指定：办公文档” reflecting the draft, and reverts when the draft is cleared