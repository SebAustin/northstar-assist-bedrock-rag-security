# Northstar Assist: Build and Secure an AWS Bedrock RAG AI Agent

Submission for the Udacity AI Security Engineer project. Start here.

## The seven deliverables

Each is in this folder (`submission/`) as a PDF and as a Word document with the same name.

| Task | Rubric item | File |
|---|---|---|
| 1 | Working harness: prompt answered, knowledge-base retrieval shown, sync without errors | `Task1_Working_Harness_Evidence` |
| 2 | ML-BOM (official template, completed) | `Task2_ML-BOM` |
| 3 | STRIDE-ML threat model (official template, completed) | `Task3_STRIDE-ML_Threat_Model` |
| 4 | IAM hardening summary: before and after, wildcards justified | `Task4_IAM_Hardening_Summary` |
| 5 | Safety controls: Bedrock Guardrails on input and output, thresholds, limitations | `Task5_Safety_Controls` |
| 6 | Monitoring plan with AI-specific signals and alert thresholds, and the prompt-injection incident playbook with console paths and CLI | `Task6_Monitoring_Plan_and_IR_Playbook` |
| 7 | Launch-readiness report: edge-case prompts, observed behaviour, recommendation | `Task7_Launch_Readiness_Report` |

## Where to find the main evidence

| What the rubric asks for | Where |
|---|---|
| The agent answers a prompt | Task 1, sections 3 and 4; `evidence/task1/playground_answer.jpg` |
| The answer uses knowledge-base retrieval | Task 1, section 4; `evidence/task1/playground_retrieve_trace.jpg` |
| Knowledge base synced without errors (30 of 30 documents) | Task 1, section 2; `evidence/task1/kb_sync.jpg`, `kb_details.jpg` |
| Original and scoped IAM policies | Task 4, sections 3 to 6 |
| Guardrail blocking and masking | Task 5, section 6; `evidence/task5/*.jpg` |
| A concrete alert threshold | Task 6, section 4 (for example more than 5 prompt-attack blocks in 1 hour); `evidence/task6/alarm_state.jpg` |
| Incident playbook with console paths and CLI | Task 6, section 7 |
| At least three edge-case prompts with observed behaviour | Task 7, section 4 (six cases) |
| Approve, approve with conditions, or block | Task 7, sections 1 and 6: **approve with conditions** |

## Stand-out extras

| Extra | Where |
|---|---|
| CloudWatch alarms (four, one shown in ALARM) | Task 6, section 4 |
| OWASP LLM Top 10 test suite: 24 cases, three runs each, before and after hardening | Task 7, sections 2 and 3 |
| Expanded threat model (22 threats) | Task 3 |
| Streamlit monitoring dashboard | Task 7, section 5; `evidence/task7/dashboard_cloudwatch.jpg` |

## Rest of the repository

- `evidence/`: screenshots and raw evidence files by task. The screenshots are also embedded in the reports.
- `infra/`, `tools/`, `tests/`, `guardrail/`, `iam/`, `monitoring/`, `redteam/`, `streamlit_app/`: the scripts, definitions, test suite and dashboard.
- `results/`: every test run, before and after hardening.
- `README.md` at the repository root explains the layout; `ACCEPTANCE.md` maps each requirement to its evidence.

## Notes for the reviewer

- All AWS resources were created in the Udacity Cloud Lab account and were deleted after the evidence was captured, as the course requires. `evidence/teardown/` holds the proof.
- The knowledge-base documents are the course's fictional sample data.
- Source repository: https://github.com/SebAustin/northstar-assist-bedrock-rag-security
