# Spec Delta

## Purpose

Enforces authentication, role-based access control (RBAC), per-merchant tenant isolation, PCI-DSS sensitive-data sanitization, and API rate/token-budget governance across chat, observability, evaluation, and human-handoff endpoints.

## ADDED Requirements

### Requirement: Bearer Token Authentication on Protected Endpoints
The system SHALL require a valid signed Bearer token on all chat, chat history, observability, evaluation, and human-handoff endpoints, rejecting missing, malformed, or expired credentials with HTTP `401 Unauthorized`.

#### Scenario: Unauthenticated request to chat, traces, or history rejected
- **WHEN** a client sends `POST /chat`, `GET /traces`, or `GET /chat/history/cliente1988` without an `Authorization: Bearer <token>` header
- **THEN** the API returns HTTP `401 Unauthorized` without invoking agents or exposing trace or conversation data

#### Scenario: Invalid or expired Bearer token rejected
- **WHEN** a client sends `GET /metrics` with an invalid signature or expired Bearer token
- **THEN** the API returns HTTP `401 Unauthorized`

### Requirement: Role-Based Access Control (RBAC) for Operators and Merchants
The system SHALL enforce role claims (`merchant`, `operator`, `admin`) so operational telemetry, alerts, evaluations, dashboard, and handoff-resumption endpoints are accessible only to `operator` or `admin` roles, returning HTTP `403 Forbidden` for `merchant` tokens.

#### Scenario: Merchant token blocked from observability and eval endpoints
- **WHEN** a client authenticated with role `merchant` sends `GET /traces`, `GET /alerts`, `GET /metrics`, `GET /dashboard`, `GET /handoffs`, or `POST /evals/run`
- **THEN** the API returns HTTP `403 Forbidden`

#### Scenario: Operator or admin token accesses observability endpoints
- **WHEN** a client authenticated with role `operator` or `admin` sends `GET /traces`, `GET /alerts`, or `GET /metrics`
- **THEN** the API returns HTTP `200 OK` with the requested operational data

### Requirement: Multi-Tenant User Isolation on Chat and History Routes
The system SHALL restrict `merchant` tokens to posting chat requests and accessing or clearing chat histories matching their authenticated `user_id` subject, while permitting `operator` and `admin` roles to inspect merchant records for authorized support.

#### Scenario: Merchant attempts to read, chat as, or delete another merchant's session
- **WHEN** a client authenticated as `user_id="cliente1988"` with role `merchant` sends `POST /chat` with `user_id="outro_lojista"` or requests `GET /chat/history/outro_lojista` or `DELETE /chat/history/outro_lojista`
- **THEN** the API returns HTTP `403 Forbidden`

#### Scenario: Merchant accesses their own chat and history
- **WHEN** a client authenticated as `user_id="cliente1988"` with role `merchant` sends `POST /chat` or `GET /chat/history/cliente1988` for `cliente1988`
- **THEN** the API returns HTTP `200 OK` scoped strictly to `cliente1988`'s records

### Requirement: PCI-DSS Sensitive Data Sanitization in Logs and Traces
The system SHALL mask sensitive personal and financial identifiers (such as 13-to-19-digit PANs, CVVs, CPFs/CNPJs, and Bearer credentials) before persisting or emitting structured logs, guardrail previews, and execution trace records.

#### Scenario: Card PAN masked in trace input preview and structured log
- **WHEN** a request payload contains a raw 16-digit card number, CPF, or Bearer secret
- **THEN** persisted trace records (`GET /traces/{trace_id}`) and emitted JSON logs contain only the masked representation

### Requirement: Input Bounds, Rate Limiting, and Token Budget Enforcement
The system SHALL enforce bounded message lengths on `POST /chat`, per-principal sliding-window rate limits, and configurable per-user/per-request LLM token budgets, rejecting abusive traffic with HTTP `429 Too Many Requests` or HTTP `422 Unprocessable Entity` and recording budget alerts.

#### Scenario: Oversized message rejected at validation
- **WHEN** an authenticated client submits `POST /chat` with a `message` exceeding the configured maximum character limit
- **THEN** the API returns HTTP `422 Unprocessable Entity` without invoking the orchestration graph

#### Scenario: Excessive request rate or exhausted token budget throttled
- **WHEN** an authenticated caller exceeds the configured request rate window or daily token budget
- **THEN** the API returns HTTP `429 Too Many Requests` with a `Retry-After` header and records a budget/rate alert
