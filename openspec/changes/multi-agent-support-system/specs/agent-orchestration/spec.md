# Spec Delta

## Purpose

Defines the multi-agent orchestration workflow that receives incoming user messages, classifies intent via a Router Agent, dispatches work to one or more specialized agents in sequence, and synthesizes the final response through a Personality Agent.

## ADDED Requirements

### Requirement: Router Agent Intent Classification and Dispatch
The Router Agent SHALL serve as the primary entry point for all validated user requests and MUST route each message to the Knowledge Agent, the Customer Support Agent, the Human Escalation Agent, or an ordered sequence of specialized agents based on the message intent.

#### Scenario: Product or general knowledge inquiry routed to Knowledge Agent
- **WHEN** a user submits a message asking about Getnet products, payment methods, or general real-time facts (e.g., `"What's the difference between the Get Clássica and the Get Smart?"`)
- **THEN** the Router Agent classifies the intent as `knowledge` and dispatches the request to the Knowledge Agent

#### Scenario: Account-specific or terminal issue routed to Customer Support Agent
- **WHEN** a user submits a message about their sales deposits, POS connectivity, or transaction declines along with a `user_id` (e.g., `"When will the money from yesterday's sales be deposited?"`)
- **THEN** the Router Agent classifies the intent as `customer_support` and dispatches the request with `user_id` to the Customer Support Agent

#### Scenario: Hybrid multi-intent message routed sequentially
- **WHEN** a user submits a message combining a general product question and an account-specific status inquiry
- **THEN** the Router Agent schedules both the Knowledge Agent and the Customer Support Agent in sequence and aggregates their intermediate outputs

### Requirement: Inter-Agent Context and State Propagation
The orchestration workflow SHALL maintain a structured conversation state across all participating agents in a request lifecycle, preserving the original `message`, `user_id`, intermediate agent outputs, tool invocations, retrieved citations, and routing decisions.

#### Scenario: Downstream agent accesses upstream state
- **WHEN** a specialized agent finishes executing its tools and produces an intermediate response
- **THEN** the orchestration state records the agent name, tool execution results, and confidence score so downstream agents can read them without data loss

### Requirement: Personality and Output Synthesis Agent
The system SHALL pass all specialized agent outputs through a Personality Agent before returning the final response, ensuring a consistent, empathetic, and clear Getnet support tone in the language of the user's message.

#### Scenario: Technical tool output formatted into merchant-friendly response
- **WHEN** the Customer Support Agent returns raw settlement timestamps or POS error codes for `cliente1988`
- **THEN** the Personality Agent transforms the raw data into a polite, actionable answer tailored to the merchant while preserving factual accuracy
