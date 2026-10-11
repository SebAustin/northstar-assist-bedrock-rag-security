# REQUIREMENTS: Northstar Assist (deploy, harden, validate)

Scope: deploy a RAG agent (AgentCore Harness with Claude Haiku 4.5, AgentCore Gateway with IAM inbound auth, Managed KB with Titan Text Embeddings V2 over 30 S3 docs, Bedrock Guardrail, CloudWatch), harden it, and produce the 7 Udacity deliverables plus 4 stand-out extras.
Job to be done: a security engineer proves the agent is useful (grounded answers from the KB), least-privilege, guarded against untrusted input and output, observable, and fit (or not) for launch.
Paths are relative to the project root. Layout and slices are defined in PLAN.md; open assumptions in ASSUMPTIONS.md (A1-A7).

## Functional requirements

| ID | Requirement | Task |
|---|---|---|
| FR-1 | Upload the 30 starter docs (csv, docx, html, pdf, txt, xlsx) to a private S3 bucket (public access blocked, SSE-S3) and confirm object count is 30. | 1 |
| FR-2 | Create and sync a Managed KB (Titan Text Embeddings V2); the sync finishes with 0 failed documents. | 1 |
| FR-3 | Create a Gateway (IAM inbound auth) with the Managed KB as a target (Standard retrieval). | 1 |
| FR-4 | Create a Harness (Claude Haiku 4.5, system prompt, memory off) wired to the Gateway. It answers a prompt with the FM and incorporates retrieved KB content. | 1 |
| FR-5 | Capture invocation evidence: Retrieve tool call, retrieved chunks, source document name, answer text. | 1 |
| FR-6 | Produce an ML-BOM in the provided docx template: system overview plus entries for the FM, embedding model, knowledge source, storage/retrieval services and IAM roles. Each entry has type, provider, intended use, limitations/transparency gaps. | 2 |
| FR-7 | Produce a STRIDE-ML threat model in the provided docx template: assets, trust boundaries across the agent and retrieval path, prioritised risks. | 3 |
| FR-8 | Expanded threat model: multi-turn evasion, model extraction, embedding supply chain, plus DoS/cost. | 3 (extra) |
| FR-9 | Snapshot the original harness default role and gateway default role policies, then apply scoped replacements. Document original vs. scoped, with rationale for any remaining wildcard. | 4 |
| FR-10 | Prove scoping: `simulate-principal-policy` allow/deny matrix and `accessanalyzer validate-policy`. The functional smoke prompt still passes after scoping. | 4 |
| FR-11 | Create and version a Bedrock Guardrail with prompt-attack, content filters, denied topics, PII and contextual grounding. Attach it to the harness through the `guardrailConfig` additional parameter. | 5 |
| FR-12 | Document each control's effect, threat mitigated (STRIDE-ML ID), threshold and limitations. Cover both untrusted input and untrusted output. | 5 |
| FR-13 | Harden the system prompt (retrieved content treated as untrusted data, instruction hierarchy). | 5 |
| FR-14 | Monitoring plan: named log sources and metrics, at least 1 AI-specific signal, at least 1 concrete alert threshold. Enable model invocation logging to CloudWatch. | 6 |
| FR-15 | CloudWatch alarms with the alarm JSON included (prompt-attack rate, zero-retrieval rate, token spike). | 6 (extra) |
| FR-16 | Prompt-injection IR playbook with containment and investigation phases. Every step names a console path and a CLI command. | 6 |
| FR-17 | Run at least 3 edge-case prompts in different risk categories; record observed behaviour, guardrail intervention, appropriateness. | 7 |
| FR-18 | Launch-readiness report ending in approve / approve-with-conditions / block, with rationale tied to evidence. | 7 |
| FR-19 | Test suite of 10 or more prompts mapped to OWASP LLM01-LLM10, expected-vs-actual matrix, each prompt run 3 times, inconsistency flagged. Includes a gated, labelled, removable synthetic poisoned doc for indirect injection. | 7 (extra) |
| FR-20 | Streamlit monitoring page showing guardrail intervention rate, token usage and retrieval success rate (plus recent blocked sessions), computed from CloudWatch Logs Insights. | extra |

## Non-functional requirements

| ID | Requirement | Verification |
|---|---|---|
| NFR-1 | Cost: total spend under $3 (lab budget $25). | Cost Explorer or Billing screenshot at close-out; Haiku only, no provisioned throughput, 7-day log retention. |
| NFR-2 | Teardown: every created resource is deleted at the end, logging disabled, nothing left billing. | `infra/99_teardown.sh` plus a verify-empty check saved to `evidence/`; runs only after the user confirms evidence is captured. |
| NFR-3 | No credentials in repo or output: no AWS keys, tokens or `APP_PASSWORD` values committed, logged or echoed. | Secret scan (grep for `AKIA`, `aws_secret`, `ASIA`) on the repo returns nothing; `.gitignore` covers `.env`. |
| NFR-4 | No PII in resource names or tags (bucket suffix is random hex; no personal name or email). | Review of the resource-name list in `evidence/`. |
| NFR-5 | Reproducibility: scripts are idempotent and re-runnable; versions pinned (venv requirements); README gives the end-to-end rebuild steps; console-only steps are in `infra/CONSOLE_CHECKLIST.md`. | A clean re-run of the scripts is a no-op or converges; README reviewed. |
| NFR-6 | Account safety: every script hard-fails unless `AWS_PROFILE=udacity`, the account differs from the personal account, and the region is `us-east-1`. | pytest guard tests against a stubbed `aws`. |
| NFR-7 | Quality: pytest passes for Python tools (stream parsing, classification, aggregations, template filler); 80% coverage target on `tools/` and dashboard aggregation code. | pytest and coverage report. |
| NFR-8 | Evidence integrity: each claim in a deliverable links to a file under `evidence/taskN/`. Sample PII in the KB is synthetic and not copied into reports beyond what is needed. | `ACCEPTANCE.md` cross-check. |
| NFR-9 | Safe testing: any AWS create/modify/delete is shown as a dry-run plan and run only after explicit user approval. | Gate log in `STATUS.md`. |

## Success criteria (one row per rubric line)

| ID | Criterion (testable) | Evidence artefact |
|---|---|---|
| SC-1 | The harness accepts a prompt and answers with an FM. Smoke prompt "What is Northstar's hybrid work policy? Name the source document." returns a non-empty answer from Haiku 4.5. | `deliverables/01_harness_evidence.md`, `evidence/task1/` transcript |
| SC-2 | The answer incorporates KB content: transcript shows a Retrieve tool call, 1 or more chunks, and the answer cites `company_policies_handbook.html`. Playground trace screenshot included. | `deliverables/01_harness_evidence.md`, `evidence/task1/` |
| SC-3 | KB sync completes with 0 failed documents and 30 of 30 sources indexed. | `evidence/task1/` sync-status screenshot or JSON |
| SC-4 | ML-BOM has entries for the FM, embedding model, knowledge source (S3 docs), storage/retrieval services (S3, Managed KB vector store, Gateway) and IAM roles (all 3 default roles). | `deliverables/ML-BOM.docx` |
| SC-5 | Every ML-BOM entry states type, provider, intended use, limitations/transparency gaps (for example undisclosed training data recorded as a finding). | `deliverables/ML-BOM.docx` |
| SC-6 | ML-BOM includes a system overview (components and data flow) that matches the deployed `get-harness` / `get-gateway` output. | `deliverables/ML-BOM.docx`, `evidence/task2/` |
| SC-7 | STRIDE-ML lists assets (with data classification) and trust boundaries covering user to harness, harness to model, harness to gateway to KB, and retrieved chunk to model context. | `deliverables/STRIDE-ML.docx` |
| SC-8 | STRIDE-ML has at least 3 prioritised risks (direct injection, indirect injection, data exposure), each with likelihood, impact, score and mitigation. | `deliverables/STRIDE-ML.docx` |
| SC-9 | At least 2 safety-control types are documented (guardrail plus system prompt, or multiple guardrail policies), each with intended effect, threat mitigated, threshold and limitation; both untrusted input and untrusted output are covered. The guardrail is attached via `guardrailConfig` (confirmed in `get-harness`). | `deliverables/05_safety_controls.md`, `guardrail/config.json`, `evidence/task5/` |
| SC-10 | IAM: original and scoped permissions are both documented. Scoped policies are limited to the needed model (Haiku 4.5 profile), KB, guardrail and gateway ARNs. No `*` action or resource unless justified in writing. The simulation matrix shows denials for other models and KBs. | `deliverables/04_iam_hardening.md`, `iam/before/`, `iam/after/`, `evidence/task4/` |
| SC-11 | Monitoring plan names specific logs and metrics, at least 1 AI-specific signal (for example guardrail interventions, zero-retrieval rate, token spike), and at least 1 concrete alert threshold (for example PROMPT_ATTACK > 5 per hour). | `deliverables/06_monitoring_and_ir.md`, `evidence/task6/` |
| SC-12 | IR playbook for prompt injection has containment (with console path and CLI) and investigation (Logs Insights queries by session or identity) sections. | `deliverables/06_monitoring_and_ir.md` |
| SC-13 | Launch-readiness covers at least 3 prompts in different risk categories with observed behaviour, guardrail intervention (yes/no, which policy), appropriateness, and a final approve / conditions / block recommendation with rationale. | `deliverables/07_launch_readiness.md`, `evidence/task7/` |
| SC-X1 | Stand-out: CloudWatch alarms exist and the alarm JSON is included. At least one alarm reaches ALARM state when attack prompts are replayed. | `deliverables/06_monitoring_and_ir.md`, `evidence/task6/` |
| SC-X2 | Stand-out: at least 10 prompts mapped to OWASP LLM01-LLM10, expected-vs-actual matrix, 3 runs each. | `redteam/prompts.yaml`, `results/matrix_hardened.md`, `deliverables/07_launch_readiness.md` |
| SC-X3 | Stand-out: expanded threat model covers multi-turn evasion, model extraction and embedding supply chain, each with scores and mitigations. | `deliverables/STRIDE-ML.docx` |
| SC-X4 | Stand-out: Streamlit page displays intervention rate, token usage and retrieval success; aggregation unit tests pass; screenshot captured. | `streamlit_app/pages/1_Monitoring.py`, `tests/`, `evidence/task7/` |
| SC-Z | Final gate: every SC row maps to an existing file, and all NFRs verified. | `ACCEPTANCE.md` |

## Constraints

- Cloud: Udacity Cloud Lab account only, `us-east-1`, AWS CLI profile `udacity` (temporary keys, rotated by the lab). Lab session limits may force re-creation of resources, so scripts must be re-runnable.
- Credential scope preflight (verify on Day 1, before S1): the lab identity needs, at minimum, create/get/update on AgentCore harness and gateway; Managed KB create/sync (console); `bedrock:CreateGuardrail` and `ApplyGuardrail`; `bedrock:PutModelInvocationLoggingConfiguration`; IAM `GetRolePolicy`, `PutRolePolicy`, `AttachRolePolicy` on the two default roles (Task 4 needs write); `logs:*` and `cloudwatch:PutMetricAlarm`; S3 bucket create/put; Bedrock access to Haiku 4.5 and Titan Text Embeddings V2. Check with `aws sts get-caller-identity`, `list-harnesses`, a dry-run of each create, and `iam simulate-principal-policy` where permitted. Record any missing capability as a risk before building. ASSUMPTIONS.md does not yet record this preflight (see open items).
- Stack: Bedrock AgentCore harness/gateway, Managed KB, Bedrock Guardrails, CloudWatch; Python in a project venv (boto3, python-docx, streamlit, pyyaml, pytest); AWS CLI 2.35.9. Managed KB creation and sync are console-only (A3); harness and gateway default roles are console-created (A2).
- Model and embeddings are fixed by the brief: Claude Haiku 4.5 (A4), Titan Text Embeddings V2, memory off.
- Templates: ML-BOM and STRIDE-ML must be filled in the provided `.docx` templates with their styles and sections kept. The other five reports are Markdown, also exported to `.docx` or PDF.
- Hybrid execution: the user performs console-only steps and supplies screenshots; the agent never handles keys.
- Guardrail limits to design around: the prompt-attack filter applies to input only; contextual grounding may not receive retrieved chunks as grounding source through the harness (to be tested and documented); Standard retrieval returns chunks, so indirect injection through documents is not fully blockable by guardrails.
- Cost control: Haiku only, 7-day log retention, run suites at N=3, delete the test document and logging when done.
- Quality bar from user rules: TDD for Python, 80% coverage, files under 800 lines, no hardcoded secrets, security review before commits.

## Non-goals

- Production deployment, custom domains, autoscaling, multi-region or HA, CI/CD.
- Any use of the personal AWS account or its `default` profile.
- Modifying the starter files (templates, `streamlit_app/app.py`, the 30 KB docs); work happens in copies, and the dashboard lives in a separate page.
- Changing the fixed model, embedding model or KB type; fine-tuning or training; building a custom vector store.
- Authentication hardening of the starter Streamlit chat app beyond a note about its plaintext `APP_PASSWORD` compare.
- Real PII, real attacks against third parties, or a permanent poisoned document in the KB.
- Memory, Browser, Code Interpreter and other harness tools (removed or left off, not extended).
- Penetration testing of AWS services themselves.

## Open items for the caller

- ASSUMPTIONS.md lacks the credential-scope preflight entries (the Constraints section above lists the scopes); add them there, since this task could modify only REQUIREMENTS.md.
- Inferred defaults not in ASSUMPTIONS.md: 80% coverage is applied to `tools/` and aggregation code only (not infra shell scripts); "approve with conditions" counts as the "conditions" verdict.
