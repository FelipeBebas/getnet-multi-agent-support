# Spec Delta

## MODIFIED Requirements

### Requirement: Getnet Knowledge Base Ingestion and Vector Indexing
The system SHALL ingest, chunk, embed (using `OpenAIEmbeddings` when configured), and persist content from official Getnet web pages (`https://www.getnet.net/en` and `https://site.getnet.com.br` subpages) together with a validated ground-truth corpus covering the full POS terminal portfolio (*Get Tap*, *Get Mini*, *Get Lite*, *Get Clássica*, and *Get Smart*), *Pix*, *Antecipação de Recebíveis*, *Crediário*, and *Payment Link (GetPay)* into a persistent vector store.

#### Scenario: Knowledge base initialization on startup or CLI command
- **WHEN** the ingestion pipeline runs against configured Getnet URLs (`getnet.net/en` and `site.getnet.com.br` product/FAQ URLs) and curated ground-truth corpus documents
- **THEN** the system chunks the text with metadata (`source_url`, `title`, `topic`) and stores vector embeddings ready for semantic similarity search

### Requirement: Grounded Product Retrieval and Generation (RAG)
The Knowledge Agent SHALL query the Getnet vector store to answer questions about Getnet hardware, services, fees, and settlement rules, grounding its response in the retrieved chunks without using hardcoded `if/elif` canned English templates, recording source citations, and dynamically escalating to the general Web Search tool (`web_search_general`) whenever the retrieved RAG chunks do not answer the user's question (or to the Human Escalation Agent when confidence remains `< 0.60`).

#### Scenario: Comparing Get Clássica, Get Smart, and the full Getnet terminal lineup
- **WHEN** the Knowledge Agent receives `"What's the difference between the Get Clássica and the Get Smart?"` or questions about *Get Lite*, *Get Mini*, or *Get Tap*
- **THEN** it retrieves relevant terminal specification chunks and explains the differences in hardware features (physical keyboard vs. Android touch screen, coil printer, NFC), connectivity, and target business profile

#### Scenario: Answering Pix, Receivables Advance, Crediário, and Payment Link questions
- **WHEN** the Knowledge Agent receives inquiries about Pix bank account (domicílio bancário) requirements, receivables advance (*antecipação* punctual or automatic), *crediário* installment limits (up to 48x with 2-business-day merchant payout), or selling via WhatsApp Payment Link (*GetPay*)
- **THEN** it retrieves the corresponding Getnet product rules from the knowledge base and generates an accurate, grounded explanation

#### Scenario: Unrecognized entities, anti-inflation checks, and attributed citations
- **WHEN** the Knowledge Agent receives a query referencing a non-existent product or entity (e.g. `"Get Bronze Water"`)
- **THEN** the system verifies entity coverage against the Getnet catalog and domain records without concept score inflation, explicitly states that the unlisted entity does not exist in the official portfolio, and excludes unrelated search results (such as general philosophy or home decor pages) from the attributed `sources` list

#### Scenario: Discovering newly launched Getnet products via live web search fallback
- **WHEN** the Knowledge Agent receives an out-of-corpus query (e.g., `"Quando a getnet foi inaugurada?"` or a newly released Getnet product) that is absent from or not answered by the local vector store chunks
- **THEN** it discards irrelevant RAG chunks, automatically invokes live Web Search (`web_search_general`) to find the answer on the internet, propagates the true confidence score without an artificial `0.65` floor, and answers in the user's language (`pt` or `en`)

### Requirement: External Web Search Tool for General-Purpose Queries
The Knowledge Agent SHALL invoke a Web Search tool when a user query requests general-purpose or real-time external facts outside Getnet's product domain, automatically resolving relative dates (`today`, `tomorrow`) in the local timezone of the user/target city (`timezone=auto` and `datetime.now().astimezone()`) and never masking search failures with fabricated placeholder strings.

#### Scenario: Weather forecast lookup
- **WHEN** the Knowledge Agent receives `"What's the weather forecast in Porto Alegre tomorrow?"` (including late at night in the user's local timezone)
- **THEN** it resolves `tomorrow` automatically using the local timezone rather than `UTC+0`, executes the Web Search tool for Porto Alegre's weather forecast, and returns a concise summary for the exact next local calendar day

#### Scenario: Currency exchange rate lookup
- **WHEN** the Knowledge Agent receives `"What's the euro exchange rate today?"`
- **THEN** it executes the Web Search tool to retrieve the current Euro exchange rate and reports the value with source attribution
