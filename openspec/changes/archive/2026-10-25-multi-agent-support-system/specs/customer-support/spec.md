# Spec Delta

## Purpose

Resolves merchant-specific support inquiries by equipping the Customer Support Agent with domain tools that retrieve account settlements, POS terminal diagnostics, transaction decline records, and support tickets for a given `user_id`.

## ADDED Requirements

### Requirement: Merchant Settlement and Receivables Lookup Tool
The Customer Support Agent SHALL provide a tool that retrieves a merchant's settlement schedule, pending deposits from recent sales, and registered payout bank account status using the request's `user_id`.

#### Scenario: Checking yesterday's sales deposit schedule for an existing merchant
- **WHEN** `cliente1988` asks `"When will the money from yesterday's sales be deposited?"`
- **THEN** the Customer Support Agent invokes the settlement lookup tool with `user_id="cliente1988"` and returns the exact deposit date, time window, amount, and payout plan

#### Scenario: Unknown user identifier lookup
- **WHEN** the settlement lookup tool is called with an unrecognized `user_id`
- **THEN** the tool returns a structured not-found status and the agent informs the user while offering general settlement timelines

### Requirement: POS Terminal Connectivity and Transaction Decline Diagnostic Tool
The Customer Support Agent SHALL provide a diagnostic tool that inspects a merchant's registered card machines, network connectivity telemetry, and recent transaction decline codes for the given `user_id`.

#### Scenario: Troubleshooting card machine internet connectivity
- **WHEN** `cliente1988` asks `"My card machine won't connect to the internet, what should I do?"`
- **THEN** the Customer Support Agent invokes the terminal diagnostic tool for `cliente1988` and provides step-by-step Wi-Fi/SIM troubleshooting tailored to their registered terminal model

#### Scenario: Diagnosing a transaction decline error on the card machine
- **WHEN** `cliente1988` states `"My card machine is showing a transaction decline error."`
- **THEN** the Customer Support Agent invokes the diagnostic tool for `cliente1988`, identifies the specific decline code on the latest transaction, explains the cause, and provides resolution steps

### Requirement: Technical Support Ticket Management Tool
The Customer Support Agent SHALL provide a tool to check existing support tickets or open a new technical assistance ticket for a `user_id` when hardware faults or persistent errors cannot be resolved through self-service steps.

#### Scenario: Opening a support ticket for persistent terminal failure
- **WHEN** terminal diagnostics indicate a hardware fault or unresolved connectivity outage for a merchant
- **THEN** the Customer Support Agent invokes the ticket tool to register or retrieve a support ticket and returns the ticket protocol number to the user
