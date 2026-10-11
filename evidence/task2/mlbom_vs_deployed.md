# ML-BOM system overview compared with the deployed configuration

Each value below was read from the `get-harness`, `get-gateway` and `get-knowledge-base` output saved in Task 1, then searched for in the text of `deliverables/ML-BOM.docx`. Generated on 2026-10-10.

| Fact | Deployed value | Read from | Appears in the ML-BOM |
|---|---|---|---|
| Harness ID | `NorthstarAssist-XSASd9gyWX` | `evidence/task1/harness.json` | yes |
| Foundation model (inference profile) | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | `evidence/task1/harness.json` | yes |
| Harness execution role | `AmazonBedrockAgentCoreHarnessDefaultServiceRole-37uao` | `evidence/task1/harness.json` | yes |
| Harness tool | `northstar-assist-gateway` | `evidence/task1/harness.json` | yes |
| Gateway ID | `northstar-assist-gateway-hd1uvsa8f3` | `evidence/task1/gateway.json` | yes |
| Gateway inbound authorisation | `AWS_IAM` | `evidence/task1/gateway.json` | yes, worded as "IAM (SigV4) inbound authorization" |
| Gateway protocol | `MCP` | `evidence/task1/gateway.json` | yes |
| Gateway role | `AmazonBedrockAgentCoreGatewayDefaultServiceRole1791659264711` | `evidence/task1/gateway.json` | yes |
| Knowledge base ID | `WUWHZC06MP` | `evidence/task1/knowledge_base.json` | yes |
| Embedding model | `amazon.titan-embed-text-v2:0` | `evidence/task1/knowledge_base.json` | yes |
| Embedding dimensions | `1024` | `evidence/task1/knowledge_base.json` | yes |
| Document bucket | `northstar-assist-kb-5ca661ad` | `evidence/task1/s3_objects.json` | yes |

**Result:** all 12 deployed values appear in the ML-BOM (11 verbatim, 1 in words).
