# Resource names: review for personal information

The Cloud Lab rules forbid personal information (names, email addresses, phone numbers) in resource names and tags.
This is every resource the project created, as listed by `infra/99_teardown.sh --plan` on 2026-10-10 (23:08 UTC),
with the names taken from `infra/state.env` and the Task 1, 5 and 6 evidence files.

| Kind | Name | Named by | Personal information |
|---|---|---|---|
| S3 bucket | `northstar-assist-kb-5ca661ad` | `infra/01_s3.sh` (random hex suffix) | none |
| Knowledge base, data source | `northstar-assist-kb`, `northstar-documents` | console, names chosen for the project | none |
| Gateway, target | `northstar-assist-gateway-hd1uvsa8f3`, `northstar-kb` | console (generated suffix) | none |
| Harness, runtime | `NorthstarAssist-XSASd9gyWX`, `harness_NorthstarAssist-92Prr07JAK` | CLI and service (generated suffix) | none |
| Guardrails | `northstar-assist-guardrail`, `northstar-assist-lockdown` | `infra/03_guardrail.sh` | none |
| IAM roles | `AmazonBedrockAgentCoreHarnessDefaultServiceRole-37uao`, `AmazonBedrockAgentCoreGatewayDefaultServiceRole1791659264711`, `AmazonBedrockExecutionRoleForKnowledgeBase_x7ne0`, `NorthstarBedrockInvocationLoggingRole` | console defaults; the last by `infra/05_monitoring.sh` | none |
| IAM policies | seven `AmazonBedrock...` policies with generated suffixes | console defaults | none |
| Log groups | `/northstar/bedrock/invocations`, the knowledge base and runtime log groups | script and service | none |
| Alarms, metric filters, saved queries | all prefixed `NorthstarAssist` | `infra/05_monitoring.sh` | none |
| Tags | `project=northstar-assist` only | scripts | none |

**Result:** no resource name or tag contains personal information. No SNS subscription was created, because it would
need an email address or phone number (assumption A17). The role session name of the lab user that appears in
screenshots and error messages is assigned by the lab, not by this project.
