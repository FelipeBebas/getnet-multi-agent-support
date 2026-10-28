# knowledge-rag Specification

## Purpose

Provides grounded answers about Getnet's products, payment solutions, and policies using Retrieval-Augmented Generation (RAG) over official Getnet content, combined with a Web Search tool for general-purpose or real-time external questions.

## Requirements

### Requirement: Getnet Knowledge Base Ingestion and Vector Indexing
The system SHALL ingest, chunk, embed, and persist content from official Getnet web pages (`https://www.getnet.net/en` and `https://site.getnet.com.br` subpages) together with a validated ground-truth corpus covering the full POS terminal portfolio (*Get Tap*, *Get Mini*, *Get Lite*, *Get Clássica*, and *Get Smart*), *Pix*, *Antecipação de Recebíveis*, *Crediário*, and *Payment Link (GetPay)* into a persistent vector store.

#### Scenario: Knowledge base initialization on startup or CLI command
- **WHEN** the ingestion pipeline runs against configured Getnet URLs (`getnet.net/en` and `site.getnet.com.br` product/FAQ URLs) and curated ground-truth corpus documents
- **THEN** the system chunks the text with metadata (`source_url`, `title`, `topic`) and stores vector embeddings ready for semantic similarity search

### Requirement: Grounded Product Retrieval and Generation (RAG)
The Knowledge Agent SHALL query the Getnet vector store to answer questions about Getnet hardware, services, fees, and settlement rules, grounding its response in the retrieved chunks, recording source citations, and falling back to a live Getnet-scoped web search when queried about newly launched or unlisted Getnet products.

#### Scenario: Comparing Get Clássica, Get Smart, and the full Getnet terminal lineup
- **WHEN** the Knowledge Agent receives `"What's the difference between the Get Clássica and the Get Smart?"` or questions about *Get Lite*, *Get Mini*, or *Get Tap*
- **THEN** it retrieves relevant terminal specification chunks and explains the differences in hardware features (physical keyboard vs. Android touch screen, coil printer, NFC), connectivity, and target business profile

#### Scenario: Answering Pix, Receivables Advance, Crediário, and Payment Link questions
- **WHEN** the Knowledge Agent receives inquiries about Pix bank account (domicílio bancário) requirements, receivables advance (*antecipação* punctual or automatic), *crediário* installment limits (up to 48x with 2-business-day merchant payout), or selling via WhatsApp Payment Link (*GetPay*)
- **THEN** it retrieves the corresponding Getnet product rules from the knowledge base and generates an accurate, grounded explanation

#### Scenario: Discovering newly launched Getnet products via live web search fallback
- **WHEN** the Knowledge Agent receives a query about a newly released Getnet product or campaign that has insufficient similarity or is absent from the local vector store chunks
- **THEN** it invokes a live web search targeted at Getnet's official domain (`site:site.getnet.com.br` / `Getnet`) to retrieve up-to-date product information and cites the discovered URL in its response

### Requirement: External Web Search Tool for General-Purpose Queries
The Knowledge Agent SHALL invoke a Web Search tool when a user query requests general-purpose or real-time external facts outside Getnet's product domain.

#### Scenario: Weather forecast lookup
- **WHEN** the Knowledge Agent receives `"What's the weather forecast in Porto Alegre tomorrow?"`
- **THEN** it executes the Web Search tool for Porto Alegre's weather forecast and returns a concise summary based on search results

#### Scenario: Currency exchange rate lookup
- **WHEN** the Knowledge Agent receives `"What's the euro exchange rate today?"`
- **THEN** it executes the Web Search tool to retrieve the current Euro exchange rate and reports the value with source attribution
