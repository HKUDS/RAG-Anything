## ADDED Requirements

### Requirement: Neutral overlay backdrops
Full-screen modal, drawer, and confirmation overlay backdrops SHALL use a neutral black tint with no blue hue, using the same alpha values as the previous blue overlays.

#### Scenario: Delete knowledge base confirmation
- **WHEN** a user opens the delete knowledge base confirmation dialog on the knowledge base page
- **THEN** the backdrop SHALL use `bg-black/20` (or equivalent `rgba(0,0,0,0.20)`) and SHALL keep the existing `blur(8px)` backdrop blur
- **AND** the backdrop SHALL NOT contain a blue hue

#### Scenario: All fixed overlay backdrops
- **WHEN** any fixed full-screen overlay opens (create knowledge base `bg-black/20`, delete agent / workflow confirm / workflow load `bg-black/25`, knowledge graph create/delete `bg-black/20`, agent config `rgba(0,0,0,0.24)`)
- **THEN** the backdrop SHALL use an equal-alpha neutral black tint with no blue hue
- **AND** the backdrop blur SHALL remain unchanged from the pre-change behavior
- **AND** dark mode SHALL keep the existing `dark:bg-black/40` overlay variant where present

#### Scenario: Drawer and dialog layers
- **WHEN** the document-detail side drawer or a user dialog layer opens
- **THEN** the layer background SHALL use `rgba(0,0,0,0.22)` for the standard layer and `rgba(0,0,0,0.28)` for confirmation layers
- **AND** no backdrop blur SHALL be added where none existed before

#### Scenario: Agent config overlay decoration
- **WHEN** the agent config overlay opens in light mode
- **THEN** the bottom gradient decoration SHALL use a neutral `rgba(0,0,0,…)` gradient with no blue hue