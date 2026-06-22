## 1. Force simulation stabilization (Core Fix)

- [x] 1.1 Configure `alphaDecay` (~0.0228) and `alphaMin` (0.001) on forceSimulation init
- [x] 1.2 Add `alpha < 0.02` check in `sim.on('tick')` to call `sim.stop()` for auto-halt
- [x] 1.3 On drag end, set `alphaTarget(0)` to trigger cooldown instead of infinite restart
- [ ] 1.4 Verify: graph nodes settle and stop moving within ~2 seconds after load or drag

## 2. Zoom controls (Functional buttons)

- [x] 2.1 Store `d3.zoom()` instance in `useRef` for external access
- [x] 2.2 Implement zoom-in button: `zoom.scaleBy(svg.transition().duration(300), 1.5)`
- [x] 2.3 Implement zoom-out button: `zoom.scaleBy(svg.transition().duration(300), 0.67)`
- [x] 2.4 Implement reset button: restore to initial fit transform with 500ms transition
- [ ] 2.5 Verify: all three buttons produce correct zoom/fit behavior

## 3. Auto-fit on load

- [x] 3.1 After simulation stops (alpha < 0.02), compute bounding box of all nodes
- [x] 3.2 Call manual `zoom.transform()` with computed scale+translate to center all nodes with 40px padding
- [x] 3.3 Save initial transform for reset button reference
- [ ] 3.4 Verify: graph loads centered with all nodes visible regardless of layout

## 4. Responsive container

- [x] 4.1 Add `ResizeObserver` on SVG parent container to track width changes
- [x] 4.2 Update SVG width/height attributes on resize
- [x] 4.3 Set minimum height 350px, use container width for SVG width
- [ ] 4.4 Verify: graph adapts when window resizes or sidebar toggles

## 5. Hover highlight

- [x] 5.1 On `mouseenter`, scale hovered node circle to 1.5× radius with D3 transition
- [x] 5.2 Reduce opacity of all non-connected nodes to 0.15 and non-connected edges to 0.15
- [x] 5.3 Increase connected edges to opacity 1.0 and stroke-width 2.5
- [x] 5.4 On `mouseleave`, reset all visual properties to defaults with smooth transition
- [x] 5.5 Show tooltip (full node name + type) near cursor on hover
- [ ] 5.6 Verify: hover/non-hover states transition smoothly, tooltip appears/disappears correctly

## 6. Drag visual feedback

- [x] 6.1 Add SVG filter (drop-shadow) for node dragging state
- [x] 6.2 On drag start: enlarge node to 1.3× radius, apply shadow
- [x] 6.3 On drag end: reset node radius (200ms transition), remove shadow, trigger cooldown
- [ ] 6.4 Verify: drag interaction feels responsive with clear visual feedback

## 7. Edge labels

- [x] 7.1 Create invisible `<path>` elements along each edge for textPath reference
- [x] 7.2 Add `<text><textPath>` elements showing Chinese relation type labels at edge midpoints
- [x] 7.3 Style labels: font-size 8px, semi-transparent warm-gray color
- [ ] 7.4 Verify: labels readable, positioned at edge midpoints, relation types correct

## 8. Final verification

- [ ] 8.1 Manual test: open knowledge graph tab, confirm no bouncing after load
- [ ] 8.2 Manual test: zoom in/out/reset buttons all functional
- [ ] 8.3 Manual test: drag nodes, hover nodes, click nodes — all interactions smooth
- [ ] 8.4 Manual test: resize browser window, confirm graph adapts
- [x] 8.5 Verify no console errors or React warnings in dev mode (build passes clean)
