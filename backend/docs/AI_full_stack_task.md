> Background reference converted from [AI_full_stack_task.docx](AI_full_stack_task.docx). The assignment text below describes the broader project; it does not expand the current backend-only implementation scope.

# Technical Assignment: Voice Analytics Agentic AI Platform

## Objective

Build a working POC of an agentic AI system that ingests user audio files, analyzes them with LLMs, and shows the results in a mobile app. Then design the production architecture for multi-region scale.

### Mobile or Web App

- Sign-up and login.
- Upload one or several audio files.
- List the user's files and analysis results. Users can filter by date, duration, taxonomy label and custom filter results.
- Users can select and configure the predefined prompt on the UI
- Save both audio and transcribed files per user

Note: Keep the UI to minimal. Its about the technical implementation, not the design itself. Use Framework by choice. Mobile integration is preferable.

### Functionality Pipeline

Layer 1: Standard prompt. This focuses on:

- duration_sec: file length in seconds
- summary: summary of the audio content
- taxonomy:
  - professional_topics[]
  - personal_topics[]
  - upcoming_events[], for the purpose of the task only flag it as upcoming

Layer 2: User-managed prompt injection. This layer is optional

- The user picks from predefined options for additional analysis (for example RMS, count all adjectives/nouns, or any other example)
- The filters are injected into the analysis of each file, and the results are stored alongside Layer 1.
- Describe your guardrails against malicious input from both the user's filter parameters and the audio content itself.

## Offline Collective Analysis

Build a separate asynchronous job that produces aggregate summaries across all of a user's files, grouped by:

- time range
- Context summary and aggregation
- user (all of the user's files)
- taxonomy label
- Or any other group by the available from the additional analysis

## Data

- All entities are keyed and partitioned by a unique user identifier (user_id, UUID).
- Deliver the DB schema and your object storage key structure.

## Scalability architecture proposal

Target: N regions, each with 10,000 registered users and 2,000 concurrent users.

Required outputs:

- Architecture block diagram showing every service: API gateway, auth, upload/object storage, queues, workers (transcription, LLM Layer 1 and 2, batch aggregation), database, cache and observability.

The candidate should define:

- Cloud provider
- the trigger (scheduled, on-demand in the UI, or both)
- how you handle large file volumes within LLM context limits
- your model choice (hosted API or self-hosted), with a justification

### Deliverables

- A Git repo with the app, backend and IaC, plus a README with setup steps.
- The deployed POC video recording of the flow from start to finish – on a mobila simulator or web local host
- Scalability sub-deliverables
