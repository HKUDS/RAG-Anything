---
name: RAG-Anything
description: AI-powered knowledge management and intelligent agent platform for education
colors:
  sky-primary: "#5b9bd5"
  sky-primary-deep: "#3f7db8"
  sky-primary-light: "#e3eef7"
  cloud-bg: "#f4f8fc"
  cloud-surface: "#ffffff"
  cloud-surface-hover: "#f8fafd"
  cloud-well: "#edf3f9"
  cloud-border: "#d6e5f2"
  cloud-border-strong: "#bcd3e8"
  ink-primary: "#264860"
  ink-body: "#2d4d66"
  ink-muted: "#557a95"
  sage-success: "#6b9e7a"
  sage-success-bg: "#f5f8f3"
  amber-warning: "#d4a853"
  amber-warning-bg: "#fdfaf3"
  rose-danger: "#c9707e"
  rose-danger-bg: "#fdf5f6"
  warm-accent: "#e8734a"
dark:
  body-bg: "#0f1d2e"
  body-text: "#c7ddf0"
  surface-bg: "sky-900/30"
  surface-border: "sky-800/20"
  muted-text: "#8da3bb"
  accent: "#6da9d7"
typography:
  body:
    fontFamily: '"IBM Plex Sans", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif'
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.625
    letterSpacing: "normal"
  title:
    fontFamily: '"IBM Plex Sans", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif'
    fontSize: "0.9375rem"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "normal"
  heading:
    fontFamily: '"IBM Plex Sans", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif'
    fontSize: "1.375rem"
    fontWeight: 600
    lineHeight: 1.875
    letterSpacing: "-0.02em"
  label:
    fontFamily: '"IBM Plex Sans", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif'
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "0.04em"
  mono:
    fontFamily: '"JetBrains Mono", "SF Mono", "Cascadia Code", monospace'
rounded:
  sm: "0.5rem"
  md: "0.75rem"
  lg: "1rem"
  full: "9999px"
spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "0.75rem"
  lg: "1rem"
  xl: "1.25rem"
  "2xl": "1.5rem"
  "3xl": "2rem"
components:
  button-primary:
    backgroundColor: "{colors.sky-primary}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "0.625rem 1.25rem"
    typography: "{typography.title}"
  button-primary-hover:
    backgroundColor: "{colors.sky-primary-deep}"
  button-secondary:
    backgroundColor: "{colors.cloud-well}"
    textColor: "{colors.ink-primary}"
    rounded: "{rounded.md}"
    padding: "0.625rem 1.25rem"
    typography: "{typography.title}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-body}"
    rounded: "{rounded.md}"
    padding: "0.5rem 1rem"
  card:
    backgroundColor: "{colors.cloud-surface}"
    rounded: "{rounded.lg}"
    padding: "1.25rem"
  input-field:
    backgroundColor: "{colors.cloud-well}"
    textColor: "{colors.ink-primary}"
    rounded: "{rounded.md}"
    padding: "0.625rem 1rem"
    typography: "{typography.body}"
---

# Design System: RAG-Anything

## 1. Overview

**Creative North Star: "云端学阁 (The Cloud Academy)"**

RAG-Anything 的设计系统以天空蓝与云白色为基调——明亮、通透、轻盈，像一缕晴空透过玻璃窗照进教室。它表达的是"科技即清晰"：不是冰冷的服务器机房，而是云端的知识随时随地触手可及。

这是一个 **Restrained** 策略的产品系统。天空蓝（Sky Blue #5b9bd5）是唯一强调色，仅用于主操作、当前选中态和状态指示器。淡蓝白（Cloud White #f4f8fc）作为全局背景——比纯白多一丝空气感，比暖色少一度体温，恰好让界面呼吸而不分心。活力珊瑚（Warm Coral #e8734a）保留为第二点缀，仅在需要传递"温暖提示"的微交互中出现——hover 状态、通知红点、友好提醒。

**Physical scene**: 一个教师在清晨的办公室，窗外是淡蓝的天空，屏幕上的界面应该像云一样安静地承载信息——不抢夺注意力，但每个按钮和链接都清晰可辨。一个学生在晚自习用平板打开 AI 助手——界面的蓝白调在暖色灯光下仍然保持清爽，文字锐利、间距宽松、操作顺手。

**Key Characteristics:**
- 天空蓝 + 云白色基调——轻盈、通透、科技感
- 单一 Sky Blue 强调色 + Warm Coral 微交互点缀（Restrained 策略）
- 阴影柔软且稀薄，仅用于区分层级——不制造视觉噪音
- 一个字体族（IBM Plex Sans），靠字重大小区分层级
- 圆角统一在 0.75rem（`rounded.md`），比传统产品 UI 更柔和
- 明确拒绝：企业软件的压抑密集、过度游戏化的少儿产品、暖色调奶油色的 AI 默认审美

## 2. Colors

整个系统建立在天空蓝-云白渐变之上。Sky Blue 是逻辑上的主角，Cloud White 是视觉上的主角。Warm Coral 作为情感温度计——极少出现，出现时必定传递温暖信号。

### Primary
- **Sky Blue** (#5b9bd5 / `sky-500`): 主按钮、当前导航选中态、链接、焦点环、进度条。OKLCH 空间约 `oklch(62% 0.1 250)`。在任一屏幕上占比不超过 10%。
- **Sky Blue Deep** (#3f7db8 / `sky-600`): hover/active 态。比主色深约 15%，按下时有清晰反馈。
- **Sky Blue Light** (#e3eef7 / `sky-100`): 选中行背景、悬浮卡片底色、信息提示区。极淡的蓝色，几乎像一片薄云。

### Neutral
- **Cloud BG** (#f4f8fc / `sky-50`): 页面背景。淡蓝白——比纯白多约 0.005 的蓝色色度。不暖不冷，刚好让白色卡片在其上"浮"起来。
- **Cloud Surface** (#ffffff / white): 卡片和面板背景。纯白 + 极轻阴影。
- **Cloud Surface Hover** (#f8fafd): 卡片和表格行的悬浮态——微弱的蓝色光泽。
- **Cloud Well** (#f0f5fa): 输入框和选中区域的凹陷背景，比 body bg 稍深，创造"下沉"感。
- **Cloud Border** (#e3eef7 / `sky-100`): 默认分割线和边框。像透过薄云的天空线。
- **Cloud Border Strong** (#c7ddf0 / `sky-200`): 输入框边框、需要更明显分离的边界。
- **Ink Primary** (#30567a / `sky-800`): 标题。深蓝灰，与 cloud-bg 形成清晰对比。
- **Ink Body** (#3a5a78): 正文颜色。与 cloud-bg 背景对比度约 5.5:1，满足 WCAG AA。带蓝色调的深色文字，比纯黑灰更轻盈。
- **Ink Muted** (#6b8aaa): 辅助文字、占位符、标签。淡蓝灰色。

### Semantic
- **Sage Success** (#6b9e7a / `sage-500`): 成功状态。bg #f5f8f3 / text #548063。
- **Amber Warning** (#d4a853 / `amber-500`): 警告。bg #fdfaf3 / text #b88c3d。
- **Rose Danger** (#c9707e / `rose-500`): 错误和危险操作。bg #fdf5f6 / text #ad5261。

### Accent
- **Warm Coral** (#e8734a / `coral-500`): 情感温度点缀——悬浮态的微交互光泽、通知红点、空状态的友好插图色、hover 卡片的微妙色彩偏移。不争夺 Sky Blue 的主操作角色。OKLCH 空间约 `oklch(65% 0.17 35)`。

### Named Rules
**The One Blue Rule.** Sky Blue (#5b9bd5) 是系统唯一的强调色。不在 UI 中引入第二个装饰色——sage/amber/rose 仅用于语义状态。Warm Coral 是情感点缀，不作为功能性强调色。

**The Cloud-Not-Cream Rule.** 页面背景 cloud-bg (#f4f8fc) 的色度偏向蓝色（OKLCH hue ≈ 240），不是暖色（hue 40-100）。这主动拒绝了 AI 生成设计的"奶油色/沙色/羊皮纸"默认。它就是一个有空气感的淡蓝白——"云"不是"暖"。

**The Coral Thermometer Rule.** Warm Coral 的出现频率 = 界面的"体温"。通知红点用 coral、hover 光泽用 coral、友好提醒用 coral。但按钮、链接、选中态、进度条只用 Sky Blue。Coral 是情绪信号，不是功能信号。

## 3. Typography

**Font Family:** IBM Plex Sans（中文回退: PingFang SC → Microsoft YaHei → system-ui）
**Mono Font:** JetBrains Mono（回退: SF Mono → Cascadia Code → monospace）

**Character:** IBM Plex Sans 带有微妙的人文气息——不像纯几何 sans 那样冷，不像人文主义 sans 那样软。它支撑 Sky Blue 的科技感而不让文字读起来像冷冰冰的终端输出。一个字体族的策略让整个产品保持一致的声音。

### Hierarchy
- **Heading** (600, 1.375rem/22px, line-height 1.875): 页面标题。每屏最多一个。`tracking-tight (-0.02em)`。
- **Title** (600, 0.9375rem/15px, line-height 1.5): 区块标题、卡片头、表单段标题。
- **Body** (400, 1rem/16px, line-height 1.625): 正文、描述、表单标签。最大行宽 65–75ch。满足 WCAG 最小正文字号。
- **Label** (500, 0.75rem/12px, letter-spacing 0.04em, uppercase): 统计标签、表格头、徽章文字。
- **Mono** (400, 继承大小): 代码片段、API 响应、技术标识符。

### Named Rules
**The Single Voice Rule.** 整个产品使用一个字体族（IBM Plex Sans），不引入 display/body 配对。Product UI 不需要第二套字体。

**The Fixed Scale Rule.** 不使用 clamp() 流体字号。产品 UI 在一致的 DPI 下被查看。

## 4. Elevation

**Philosophy: 云层级（Cloud Layering）**

这个系统使用极其柔软的阴影来表达层级。不是"卡片的阴影"，是"云层的叠透"——一层薄雾盖在另一层薄雾上。

- **静态表面（卡片、面板）**: `cloud-sm`（0 1px 3px rgba(48,86,122,0.04), 0 1px 2px rgba(48,86,122,0.03)）——几乎感知不到，仅让白色卡片从 cloud-bg 背景中微微抬起。阴影色使用 ink-primary 而非黑色，保持蓝调一致。
- **悬浮态（hover）**: 卡片升至 `cloud-md`。阴影变化传达"可交互"。
- **模态/弹窗/下拉**: `cloud-lg`（最高约 30px 模糊）。从背景中清晰分离但不戏剧化。
- **深色模式**: 阴影在深色背景下不可见。改用边框和背景色差。

### Shadow Vocabulary
- **cloud-sm** (`0 1px 3px rgba(48,86,122,0.04), 0 1px 2px rgba(48,86,122,0.03)`): 卡片、面板默认阴影。极轻。
- **cloud** (`0 4px 16px rgba(48,86,122,0.06), 0 2px 4px rgba(48,86,122,0.03)`): 悬浮卡片、下拉面板、主按钮 hover。
- **cloud-md** (`0 8px 30px rgba(48,86,122,0.08), 0 3px 8px rgba(48,86,122,0.04)`): 模态弹窗、用户菜单。
- **cloud-lg** (`0 16px 48px rgba(48,86,122,0.10), 0 4px 12px rgba(48,86,122,0.04)`): 最高层级覆盖层（极少使用）。

### Named Rules
**The Cloud Shadow Rule.** 所有阴影使用 ink-primary (#30567a) 作为阴影色——不是纯黑 `rgba(0,0,0,...)`。这保持阴影的蓝色调，让它们在云白背景上像真正的云影。如果阴影看起来不像自然光下的影子，透明度或模糊值不对。

**The Flat-By-Default Rule.** 静态表面平坦。阴影只在状态变化时出现：hover、focus、modal open。

## 5. Components

### Buttons
- **Shape:** 统一 rounded-lg（0.75rem / `rounded.md`），比传统产品 UI 的 0.5rem 更柔和——这是"温润"的体现。
- **Primary (`.btn-primary`):** 背景 Sky Blue (#5b9bd5)，白色文字。font-semibold 15px。内边距 10px 20px。cloud-sm 阴影默认。hover: 背景 Sky Blue Deep (#3f7db8) + cloud 阴影 + 向上的微位移（translateY(-1px)）。transition all 200ms ease-out。
- **Secondary (`.btn-secondary`):** 背景 cloud-well (#f0f5fa)，文字 ink-primary (#30567a)。1px cloud-border 边框。hover: 背景 cloud-border (#e3eef7)。
- **Ghost (`.btn-ghost`):** 透明背景，文字 ink-body (#3a5a78)。hover: 背景 cloud-well，文字 ink-primary。图标按钮 32×32px。
- **Danger (`.btn-danger`):** 背景 rose-50，文字 rose-600，1px rose-200 边框。
- **Disabled:** 40% 透明度 + cursor-not-allowed。

### Cards / Containers
- **Corner Style:** rounded-xl（1rem / `rounded.lg`）。比按钮稍大——卡片是容器，按钮是操作，微妙的差异创造节奏。
- **Background:** 白色 + 1px cloud-border/50 边框 + cloud-sm 阴影。
- **Hover variant:** hover 时 shadow → cloud-md，border → cloud-border-strong/60。transition-shadow 300ms。
- **Well variant:** 背景 cloud-well/80 + cloud-border/40 边框。无阴影。

### Inputs / Fields
- **Style:** 背景 cloud-well，1px cloud-border-strong/60 边框，rounded-md (0.75rem)。文字 ink-body 15px。内边距 10px 16px。
- **Focus:** 边框变 Sky Blue，背景变白色。box-shadow: 0 0 0 4px rgba(91,155,213,0.08)。transition all 200ms。
- **Placeholder:** ink-muted (#6b8aaa)。对比度约 3.8:1——在生产中应提升到 ~4.5:1 以满足 WCAG AA。

### Tags / Chips
- **Shape:** rounded-md (0.5rem)，内边距 4px 8px。字号 12px，font-medium。
- **Color variants:** sky、sage、amber、rose、purple。均为低饱和背景 + 深色文字 + 同色系边框。
- **Badges:** 圆角 full (9999px)。success (sage) / warning (amber) / error (rose) / info (sky) 四种语义色。

### Tables
- **Style:** 全宽，文字 15px。表头 12px font-medium ink-muted uppercase tracking-wider + cloud-well/50 背景 + cloud-border/60 底边框。行 hover 时 cloud-surface-hover 背景。最后一行无底边框。

### Empty States
- **Style:** 垂直居中 flex-col，py-20。大号 emoji（text-5xl，opacity-50）。标题 15px font-medium ink-muted。描述 13px ink-muted max-w-xs。

### Navigation
- **Top Bar:** 固定顶部，h-14 (56px)，背景 white/80 + backdrop-blur-md + cloud-border/50 底部边框 + cloud-sm 阴影。内容 max-w-7xl 居中。
- **Brand:** 32×32px Sky Blue 圆角图标 + "RAGAnything" 文字（display semibold 15px ink-primary）。
- **Nav Links:** 图标 + 文字，13px font-medium，rounded-md。ink-body → hover ink-primary + cloud-well 背景。active: sky-50 背景 + Sky Blue 文字。
- **User Menu:** 右侧头像圈（sky-50 背景 + Sky Blue user 图标）+ 下拉面板 card + cloud-md 阴影。

### Skeleton Loading
- **Style:** bg-gradient-to-r from cloud-border via cloud-well to cloud-border，bg-[length:200%_100%]。animate-shimmer（2s ease-in-out infinite）。rounded-md。

## 6. Dark Mode

**Toggle mechanism**: `document.documentElement.classList.toggle('dark')` (Tailwind `darkMode: 'class'` strategy).
Dark mode is built on the same sky-ink scale but inverted: deep navy surfaces replace cloud-white, cloud tints become muted blue-grays.

### Dark Palette

| Token | Value | Role |
|-------|-------|------|
| **body-bg** | `#0f1d2e` | Page background — deep sky-tinted navy (≈ sky-900 darkened to ~12% L) |
| **body-text** | `#c7ddf0` (cloud-400 / sky-200) | Body text on dark surfaces |
| **surface-bg** | `sky-900/30` | Cards, panels — translucent sky overlay |
| **surface-border** | `sky-800/20` | Card/panel borders — subtle sky tint |
| **muted-text** | `#9aaec5` (cloud-500) | Secondary text, placeholders |
| **accent** | `#6da9d7` (sky-400) | Links, active states, focus rings |

### Key Rules

- **No shadows in dark mode.** Depth comes from surface lightness, not shadow — darker surfaces recede, lighter surfaces advance.
- **Desaturate accents slightly.** Colors that pop on white can glare on dark.
- **Reduce body text weight.** Light text on dark reads heavier; the browser's default font-weight is sufficient.
- **Use the same hue.** All dark surfaces stay within the sky hue range — no warm/cool drift when toggling.

## 7. Do's and Don'ts

### Do:
- **Do** 使用 Cloud BG (#f4f8fc) 作为所有页面的统一背景——不引入第二个页面背景色。
- **Do** 将 Sky Blue (#5b9bd5) 的使用限制在 ≤10% 的屏幕面积——主按钮、当前选中态、链接、焦点环。
- **Do** 保留 Warm Coral (#e8734a) 仅用于情感微交互——通知红点、hover 光泽、友好提醒。它不抢 Sky Blue 的功能角色。
- **Do** 使用 0.75rem border-radius 作为按钮和输入框的统一圆角——0.5rem 太锐，1rem 太软。这个值刚好表达"温润"。
- **Do** 在 hover/focus 时增加阴影（cloud-sm → cloud），但静态表面保持平坦。
- **Do** 使用 ink-primary (#30567a) 作为阴影色，而非纯黑 rgba(0,0,0,...)。蓝色调的阴影在云白背景上更自然。
- **Do** 为每个交互组件实现完整的状态集：default、hover、focus、active、disabled。
- **Do** 为每个空状态提供下一步行动指引。
- **Do** 使用语义色仅用于它们对应的语义状态，Sky Blue 用于所有功能性强调。

### Don't:
- **Don't** 使用传统企业软件式的密集数据表格、无尽的表单字段、灰上加灰的菜单。如果它属于 2005 年的格子间，它就是错的。
- **Don't** 采用过度游戏化的少儿教育产品风格。不要卡通化、不要过度 gamification。
- **Don't** 使用暖色调奶油色/沙色/羊皮纸色作为背景——这是 AI 生成设计的默认。Cloud BG 是淡蓝白，不是暖白。
- **Don't** 在 body text 上使用亮灰色"为了优雅"——当对比度接近边界时，将 body color 向 ink-primary 方向推。
- **Don't** 在任何上下文中使用 `border-left` 或 `border-right` 大于 1px 的彩色侧边条。
- **Don't** 使用 gradient text (`background-clip: text`)。
- **Don't** 把玻璃态（glassmorphism）作为默认。
- **Don't** 引入第二个功能性强调色——Sky Blue 是唯一。Warm Coral 是情绪点缀，不是功能色。
- **Don't** 在不同屏幕间使用不一致的组件词汇。
- **Don't** 默认使用 modal——先穷尽 inline / progressive 替代方案。
- **Don't** 使用纯黑色或纯灰色阴影——始终从 ink-primary (#30567a) 取色。
