# Spec Delta

## MODIFIED Requirements

### Requirement: Human Escalation and Handoff Agent
The system SHALL include a fourth custom Human Escalation Agent that generates a structured human handoff payload and escalation protocol whenever a request explicitly asks for a human operator, or when an upstream agent reports resolution confidence below the configured threshold AND the request is classified under a high or medium business risk tier. Low-risk informational requests yielding low confidence SHALL complete without invoking the Human Escalation Agent.

#### Scenario: Explicit human handoff or unresolved critical issue
- **WHEN** a user requests to speak with a human attendant or an upstream agent reports a resolution confidence below the configured threshold for a high or medium risk inquiry
- **THEN** the Human Escalation Agent creates a handoff summary with conversation context, assigns a priority queue, and sets `handoff_required=true` in the response metadata

#### Scenario: Low confidence on low-risk informational inquiry
- **WHEN** an upstream agent reports a resolution confidence below the threshold on a `low` risk tier informational query (e.g., general company history, trivia, public FAQ)
- **THEN** the orchestrator terminates the agent loop without invoking the Human Escalation Agent, returns the synthesized informational response with epistemic caveats, and keeps `handoff_required=false`
