# Dashboard redesign implementation brief

## Objective

Redesign `GET /dashboard` into a polished, centered Getnet demonstration surface. It must make the actual multi-agent request lifecycle immediately understandable to an evaluator, while remaining an operational dashboard rather than a static mockup.

The existing backend API contract and live behaviour must be preserved:

- `POST /chat`
- `GET /metrics`
- `GET /alerts`
- the scenario payloads and `cliente1988`
- real response metadata (`routed_agents`, `tools_used`, `sources`, `trace_id`, `handoff_required`, and guardrail state)

Implement the frontend in React. Do not load React, fonts, icons, images, or an animation library from a remote CDN: the Dockerized dashboard must work without an additional external browser dependency. Prefer React state plus local CSS keyframes for animation; add a bundled dependency only when it materially improves the result.

## Non-negotiable content changes

1. Set the document and visible page title to exactly:

   `Mission: Getnet Multi-Agent Support System`

2. Remove the `SDD PRODUCTION READY` badge entirely.
3. Remove the empty pre-execution card headed `Synthesized Agent Response & Orchestration Metadata`.
   - Do not replace it with another empty card.
   - Render a rich execution-result panel only after a request returns.
4. Replace the flat, six-box `Linear Multi-Agent Execution Pipeline` with an interactive tree/DAG.
5. Keep the **Personality Agent** as a first-class, visible agent node named exactly `Agent 5: Personality Agent`. It is a challenge requirement and must not be renamed or removed.
6. Keep the dashboard functional: scenario selection changes the message, Execute calls the actual API, and telemetry reflects the live endpoints.

## Target information architecture

Use a centered shell with a maximum content width of 1360px (never allow cards to stretch edge-to-edge on large displays). Use 24-32px viewport gutters and a responsive one-column layout below approximately 980px.

```text
Mission header + compact live service status

Scenario console                         Agent execution map
scenario groups, user, message, CTA     interactive tree/DAG + legend

Execution result (only after a request has completed)
final answer, routing/tool/source metadata, expandable syntax-highlighted JSON

Operational telemetry
four KPIs, alerts summary, expandable raw JSON inspector
```

The visual hierarchy is deliberate: the user first selects a scenario, then sees how the system routed it, then reads the resulting customer answer and evidence. Raw JSON is supporting evidence, not the dominant visual element.

## Agent execution map

Render a responsive tree/DAG using React components and SVG connectors. The map must represent actual topology, not a decorative linear sequence:

```text
Input Guardrail
      |
Agent 1: Router Agent
  /       |          \\
Knowledge  Customer Support  Escalation
  | tools     | tools          | tool
  \\___________|________________/
       Agent 5: Personality Agent
                  |
          Output Guardrail (PCI/LGPD)
```

### Node behaviour

- Idle nodes: quiet neutral surface, readable label and concise capability label.
- During a request: mark the input guardrail and router as `running`; then update each invoked node/tool from `routed_agents` and `tools_used`.
- On success: invoked nodes receive a restrained success state, checkmark, and a short state label such as `Completed`.
- For a blocked request: Input Guardrail receives the error/block state; no downstream nodes animate or appear completed.
- For a human handoff: Escalation Agent becomes active and visually distinct, but is not styled as a failure.
- Personality Agent and Output Guardrail show their finalization state for every non-blocked response.
- Unused branches remain visibly available but subdued; never imply they ran.
- Add a compact legend: idle, running, completed, blocked.

### Information-packet microanimations

Create `FlowPacket` React elements that travel only along connectors in the active execution route. A packet is a small red/brand-colored circle with a subtle halo.

- Start packets after the request begins and sequence them with short, credible delays: ingress -> router -> selected agent/tool branch -> Personality Agent -> Output Guardrail.
- If two specialists run, animate the actual order in `routed_agents`; do not falsely animate a parallel route.
- Use CSS transforms/opacity for smooth 60fps-friendly animation. Avoid layout-affecting animation, flashing, confetti, or infinite attention-grabbing motion.
- Stop and settle the packets when the response completes.
- Respect `prefers-reduced-motion`: show state transitions without travelling packets.
- Use React state to derive the active paths and packet lifecycle. Do not hard-code a “happy path.”

## Scenario console

Keep all current scenarios but group them in visually labelled sections:

- **Getnet knowledge**: terminal comparison, Pix, antecipacao, crediario, Payment Link.
- **Live information**: weather and EUR exchange rate.
- **Merchant support**: settlement, connectivity, transaction decline.
- **Safety & orchestration**: hybrid multi-agent and guardrail attack.

Each scenario button needs a concise label and an intent tag (`Knowledge`, `Support`, `Hybrid`, or `Guardrail`). The selected scenario has an obvious selection state. Keep a freeform message field so the dashboard remains a real API tester.

The primary CTA label should be `Run scenario`. It must have loading, disabled, success, and recoverable error states.

## Result and JSON inspection

After a completed request, show a full-width `Live execution result` section:

- lead with the synthesized answer, not JSON;
- expose compact metadata chips for agents, tools, sources, trace ID, total latency, and handoff state;
- use sources as readable links/cards where URLs are available;
- put raw response JSON in a collapsed `Inspect response JSON` disclosure.

Use a React `JsonViewer` component rather than a monochrome `<pre>`. It must render JSON safely as text (no unsafe `innerHTML`) with a VS Code-inspired dark code surface and semantic tokens:

- keys: muted blue;
- strings/URLs: warm orange or green;
- numbers: light blue;
- booleans/null: purple;
- punctuation: subdued gray.

Give the telemetry inspector the same treatment under an initially collapsed `Inspect raw telemetry` disclosure. KPIs and any current alerts remain visible without needing to open it.

## Getnet visual identity

- Use the official Getnet logo asset only if it already exists locally or is explicitly supplied from the official brand guide. Do not draw an imitation logo or hotlink remote assets.
- Use `#EC0000` as the provisional accent already established in the project; verify/reconcile final brand tokens against the supplied official asset/brand guidance when available.
- Move away from the current all-dark developer-console look. Use a light, warm neutral canvas with white surfaces, near-black text, restrained borders, and brand red for primary action, active flow packets, and critical states.
- Use red sparingly: never make every button, card, and status red.
- Keep a dark code theme only inside JSON inspectors.
- Keep contrast accessible (WCAG AA minimum), visible keyboard focus, semantic buttons, and labels for diagram state.

Consult `design-style.md` for the exact visual system and interaction rules.

## Engineering constraints and validation

- Preserve the FastAPI routes and existing JSON response schema.
- Keep the implementation testable and avoid introducing a network dependency at dashboard render time.
- Ensure layout works at 1440px and 1024px widths, and stacks cleanly on mobile.
- Add/adjust focused tests for the dashboard page and preserve current API/integration tests.
- Manually verify these paths: knowledge query, support query, hybrid query, guardrail-blocked query, and explicit/low-confidence escalation.
- Do not modify agent behaviour merely to make the animation look impressive. The diagram is a faithful renderer of returned execution metadata.

## Definition of done

- The page is centered and calm on a 1920px-wide screen.
- The exact mission title is present.
- The badge and pre-execution response box are gone.
- The Personality Agent is visibly present and activated on every safe response.
- The active route, including tools, can be understood from the animation without reading raw JSON.
- JSON is readable and syntax-highlighted but secondary to the response.
- The dashboard still uses live API data end to end.
