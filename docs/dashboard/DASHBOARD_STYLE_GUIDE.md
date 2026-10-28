# Getnet Multi-Agent Dashboard - Design Style

## Design intent

This dashboard is a product-quality demonstration of a trustworthy payment-support system. It should feel clear, confident, human, and operationally credible - not like an all-purpose developer console.

The main story is:

> A merchant question is protected, intelligently routed, resolved by the right specialists, and returned in a clear Getnet voice.

Every visual decision should make that story easier to follow.

## Brand use

Use the official Getnet mark only when an approved local asset is available. Never recreate or approximate the mark with custom drawing. The official Getnet brand guide is the source of truth for supplied logos, iconography, imagery, and final palette decisions.

Until an approved token set is supplied, use the following implementation palette. `--brand-red` reflects the red already used in the existing dashboard and is a provisional token, not a replacement for the brand guide.

```css
:root {
  --brand-red: #EC0000;
  --brand-red-hover: #C90000;
  --brand-red-soft: #FDE8E7;

  --canvas: #F7F6F5;
  --surface: #FFFFFF;
  --surface-subtle: #FBFAF9;
  --ink: #161616;
  --ink-secondary: #5F5C5A;
  --ink-tertiary: #837E7B;
  --line: #E4E0DE;
  --line-strong: #CFC9C5;

  --success: #137A45;
  --success-soft: #E8F5EE;
  --warning: #9A5D00;
  --warning-soft: #FFF4D6;
  --danger: #B42318;
  --danger-soft: #FDEBEA;
  --info: #1A5FB4;
  --info-soft: #EAF2FF;

  --code-bg: #101218;
  --code-surface: #171A21;
  --code-text: #D8DEE9;
  --code-key: #81A1C1;
  --code-string: #A3BE8C;
  --code-number: #88C0D0;
  --code-boolean: #B48EAD;
  --code-punctuation: #8F9AA8;
}
```

## Layout

- Page canvas: `var(--canvas)`.
- Main shell: `max-width: 1360px; margin-inline: auto; padding: 28px 24px 48px`.
- Desktop grid: scenario console occupies 5 columns; execution map occupies 7 columns.
- Grid gap: 24px. Card gap: 20-24px.
- At 980px or less, stack to one column. Do not horizontally scroll normal content; the SVG execution map must scale or reorganize.
- Use full-width sections only within the centered shell, never across the entire viewport.

## Typography

Use the system sans-serif stack unless a licensed/local Getnet typeface is supplied.

```css
font-family: Inter, "Segoe UI", Roboto, Arial, sans-serif;
```

- Page title: 32-36px, 700, tight tracking. Exact text: `Mission: Getnet Multi-Agent Support System`.
- Supporting header text: 15-16px, `--ink-secondary`.
- Section titles: 18-20px, 650-700.
- Card labels and metadata: 12-13px, medium weight, never all caps except compact status tags.
- Body and response: 15-16px with 1.5-1.6 line-height.

Avoid excessive bold text. Hierarchy comes from scale, spacing, and contrast.

## Surfaces and components

### Header

- Place optional official Getnet logo at left, then mission title and supporting sentence.
- At right, display one small truthful service indicator, such as `Service healthy`; do not use aspirational status badges.
- Use a 1px divider below, not a large red rule.

### Cards

- White or `--surface-subtle` background.
- 1px `--line` border; 14-16px radius.
- Soft, restrained shadow only on hover or when a card contains active execution.
- Padding: 20-24px.
- Cards must earn their presence; do not render empty placeholders.

### Buttons and controls

- Primary: `--brand-red`, white label, 10px radius, 44px minimum touch target.
- Secondary: white/neutral surface and `--line-strong` border.
- Scenario chips: compact neutral buttons with selected red outline/soft-red fill; never turn every chip into a filled red button.
- Use a 2px focus ring with sufficient contrast. Hover and press states are subtle (120-180ms).

### Metadata tags

Use small, readable pills for route type, agent, tool, and status. Tags use soft semantic backgrounds; they are labels, not primary controls.

## Execution map

The tree is the dashboard's hero artifact. It must have visual breathing room and a fixed, understandable reading direction: top to bottom.

- Nodes: 148-180px wide on desktop, with title, short role, and state label.
- SVG connectors: 2px neutral `--line-strong` when idle; use red or semantic status color only for the executed path.
- Tool nodes: smaller secondary nodes nested beneath their owning specialist.
- The Personality Agent is mandatory as the convergence node. Label it exactly `Agent 5: Personality Agent`.
- State colors:
  - idle: neutral gray;
  - running: brand red with a quiet halo;
  - completed: success green and checkmark;
  - blocked: danger red;
  - escalation/handoff: warning amber.

No permanent glowing effects. Motion and glow must communicate current execution, then settle.

## Motion

Motion explains cause and effect; it must never become decoration.

- Standard transition: 160-240ms, `ease-out`.
- Flow packet travel: 450-700ms per connector; short stagger between steps.
- Node activation: opacity + border/color + small 1.01 scale maximum.
- Avoid continuous loops after execution, bounce effects, spinning loaders longer than necessary, and large movement.
- Support `prefers-reduced-motion: reduce` by disabling travel animations and showing instantaneous state changes.

## Response and data presentation

### Live execution result

- It is conditionally rendered after a request completes.
- The synthesized customer answer is the largest element.
- Supporting facts appear below as metadata tags, source links, and an expandable technical detail region.
- Empty/loading/error states should be explicit and compact, not full blank panels.

### JSON inspector

- Dark code surface, 12-13px monospaced type, 1.55 line-height.
- Use safe React rendering of tokens, not HTML injection.
- Defaults closed under a labelled disclosure: `Inspect response JSON` or `Inspect raw telemetry`.
- Color is semantic and restrained: blue keys, green/orange strings, cyan numbers, purple booleans/null, gray punctuation.
- Include copy affordance only if it can be implemented accessibly and without distracting from the demo.

## Accessibility and responsive requirements

- WCAG AA color contrast for text and all status communication.
- Never communicate state with color alone: pair it with a label, icon, or text.
- Diagram nodes are keyboard reachable and expose state/role through accessible labels.
- Buttons, disclosure controls, textarea, and input have visible focus.
- The diagram must remain legible at 1024px and become a vertically ordered flow on small screens.
