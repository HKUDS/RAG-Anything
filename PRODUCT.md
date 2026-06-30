# Product

## Register

product

> **Note**: The primary surface is app UI (dashboards, knowledge management, agent configuration). A secondary brand surface (landing/onboarding) may be needed for student-facing entry points.

## Users

**Primary: Teachers and school administrators** — They manage knowledge bases, configure AI agents for courses, monitor student usage, and maintain the content ecosystem. Their context is a working school day: they need efficiency without cognitive overhead, quick access to management functions, and clear feedback on system status.

**Secondary: Students** — They use AI agents to search knowledge, ask questions, and learn. Their context is a learning environment: they need simple, inviting, distraction-free interactions. The interface should feel like a helpful tutor, not a complex tool.

**Tertiary: System administrators** — They manage users, permissions, and system health.

## Product Purpose

RAG-Anything is an AI-powered knowledge management and intelligent agent platform for education. It allows schools to build knowledge bases from documents, configure AI agents that reason over those knowledge bases, and deliver intelligent Q&A and learning experiences to students.

**Success looks like**: Teachers spend less time answering repetitive questions; students get instant, accurate, contextual answers; the platform feels as natural as asking a teaching assistant.

## Brand Personality

**智能 (Intelligent), 现代 (Modern), 科技 (Tech-forward), 亲和 (Approachable)**

- Intelligent: The platform shows its AI capabilities through thoughtful behavior, not technical jargon. Smart defaults, predictive suggestions, context-aware responses.
- Modern: Clean, contemporary, but not chasing design fads. The interface should feel current in 2026, not frozen in 2020.
- Tech-forward: Light blue-white palette with sky-blue accents signals precision and innovation. The aesthetic is cloud-platform, not office-suite — airy, bright, confident. Technology that feels like clarity, not complexity.
- Approachable: Rounded forms, soft shadows, friendly micro-interactions keep the blue-white palette from feeling cold. A student should feel welcomed, not intimidated; a teacher should feel empowered, not overwhelmed.

## Anti-references

- **Traditional enterprise software**: No dense data tables, no endless form fields, no gray-on-gray menus, no SAP/Oracle-era information density. If it looks like it belongs in a 2005 cubicle, it's wrong.
- **Overly playful ed-tech**: Not cartoonish, not gamified-to-exhaustion. The tone is warm but respects the intelligence of both teachers and students.
- **Developer-tool aesthetic**: Not terminal-dark, not monospaced-everywhere, not "hacker" culture. This is for educators and learners, not just engineers.

## Design Principles

1. **Clarity over density** — Breathe. Group related information. Prioritize what matters on each screen. Anti-enterprise: every pixel doesn't need to earn its rent.

2. **Intelligence made visible** — AI capabilities should be discoverable, not hidden. Show what the system knows, what it's doing, and why it's giving that answer. Transparency builds trust.

3. **Teachers first, students welcomed** — The management interface gives teachers power and efficiency. The student-facing surface is simpler and more inviting. Both feel like the same product.

4. **Accessible by default** — WCAG AA is the baseline, not an afterthought. Every color choice, every interaction, every animation must pass. The platform serves diverse learners; the interface must too.

5. **Warm tech** — Sky-blue clarity without corporate coldness. Rounded over sharp. Soft shadows over hard dividers. Human language over system language. The technology feels advanced but the experience feels gentle. Professional enough for a faculty meeting, inviting enough for a 14-year-old's first interaction.

## Accessibility & Inclusion

- **Target**: WCAG 2.2 AA compliance
- **Contrast**: Minimum 4.5:1 for body text, 3:1 for large text (≥18px or bold ≥14px)
- **Keyboard**: Full keyboard navigation support for all interactive elements
- **Screen readers**: Semantic HTML, ARIA labels, meaningful alt text
- **Motion**: Respect `prefers-reduced-motion`; all animations must have reduced-motion fallbacks
- **Color**: No color-alone information encoding; ensure readability for common color vision deficiencies
- **Language**: Primary UI in Chinese (Simplified), with i18n readiness for future localization
