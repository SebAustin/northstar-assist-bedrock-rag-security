# Northstar Assist: Build and Secure an AWS Bedrock RAG AI Agent

Submission for the Udacity AI Security Engineer project. Start here.

## The seven deliverables

Word documents in this folder. Every screenshot is embedded in the report it belongs to.

| Task | Rubric item | File |
|---|---|---|
| 1 | Working harness: prompt answered, knowledge-base retrieval shown, sync without errors | `Task1_Working_Harness_Evidence.docx` |
| 2 | ML-BOM (official template, completed) | `Task2_ML-BOM.docx` |
| 3 | STRIDE-ML threat model (official template, completed) | `Task3_STRIDE-ML_Threat_Model.docx` |
| 4 | IAM hardening summary: before and after, wildcards justified | `Task4_IAM_Hardening_Summary.docx` |
| 5 | Safety controls: Bedrock Guardrails on input and output, thresholds, limitations | `Task5_Safety_Controls.docx` |
| 6 | Monitoring plan with AI-specific signals and alert thresholds, and the prompt-injection incident playbook with console paths and CLI | `Task6_Monitoring_Plan_and_IR_Playbook.docx` |
| 7 | Launch-readiness report: edge-case prompts, observed behaviour, recommendation | `Task7_Launch_Readiness_Report.docx` |

## Where to find the main evidence

| What the rubric asks for | Where |
|---|---|
| The agent answers a prompt | Task 1, sections 3 and 4 |
| The answer uses knowledge-base retrieval | Task 1, section 4 |
| Knowledge base synced without errors (30 of 30 documents) | Task 1, section 2 |
| Original and scoped IAM policies | Task 4, sections 3 to 6 |
| Guardrail blocking and masking | Task 5, section 6 |
| A concrete alert threshold | Task 6, section 4 (for example more than 5 prompt-attack blocks in 1 hour) |
| Incident playbook with console paths and CLI | Task 6, section 7 |
| At least three edge-case prompts with observed behaviour | Task 7, section 4 (six cases) |
| Approve, approve with conditions, or block | Task 7, sections 1 and 6: **approve with conditions** |

## Stand-out extras

| Extra | Where |
|---|---|
| CloudWatch alarms (four, one shown in ALARM) | Task 6, section 4 |
| OWASP LLM Top 10 test suite: 24 cases, three runs each, before and after hardening | Task 7, sections 2 and 3 |
| Expanded threat model (22 threats) | Task 3 |
| Streamlit monitoring dashboard | Task 7, section 5 |

## Code and raw evidence

`code/` holds the scripts, guardrail and IAM definitions, monitoring definitions, the test suite and the dashboard. It contains no third-party libraries. The raw evidence files, PDF copies of the reports and the full test results are in the source repository:

https://github.com/SebAustin/northstar-assist-bedrock-rag-security

All AWS resources were created in the Udacity Cloud Lab account and deleted after the evidence was captured.
