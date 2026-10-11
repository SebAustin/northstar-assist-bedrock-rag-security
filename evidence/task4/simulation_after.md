| Role | Action | Resource | Why it matters | Decision |
|---|---|---|---|---|
| HARNESS | `bedrock:InvokeModelWithResponseStream` | `bedrock:us-east-1:609617804976:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0` | The approved inference profile, with the Northstar guardrail attached | allowed |
| HARNESS | `bedrock:InvokeModelWithResponseStream` | `bedrock:us-east-1:609617804976:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0` | The approved profile called WITHOUT the Northstar guardrail (per-request override) | explicitDeny |
| HARNESS | `bedrock:InvokeModelWithResponseStream` | `bedrock:us-east-1:609617804976:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0` | The approved profile called with some other guardrail | explicitDeny |
| HARNESS | `bedrock:InvokeModelWithResponseStream` | `bedrock:us-east-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0` | Haiku 4.5 in a destination Region, called through the profile, with the Northstar guardrail attached | allowed |
| HARNESS | `bedrock:InvokeModelWithResponseStream` | `bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0` | Haiku 4.5 called directly, not through the profile | explicitDeny |
| HARNESS | `bedrock:InvokeModelWithResponseStream` | `bedrock:us-east-1:609617804976:inference-profile/us.amazon.nova-2-lite-v1:0` | A different model's inference profile | explicitDeny |
| HARNESS | `bedrock:InvokeModel` | `bedrock:us-east-1::foundation-model/amazon.nova-2-lite-v1:0` | A different foundation model | explicitDeny |
| HARNESS | `bedrock:InvokeModel` | `bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0` | A larger, costlier model | explicitDeny |
| HARNESS | `bedrock:ApplyGuardrail` | `bedrock:us-east-1:609617804976:guardrail/753a9dgwqe2f` | The Northstar guardrail | allowed |
| HARNESS | `bedrock:ApplyGuardrail` | `bedrock:us-east-1:609617804976:guardrail/1oom74pzn70o` | The IR lockdown guardrail | allowed |
| HARNESS | `bedrock:ApplyGuardrail` | `bedrock:us-east-1:609617804976:guardrail/aaaaaaaaaaaa` | Any other guardrail | implicitDeny |
| HARNESS | `bedrock-agentcore:InvokeGateway` | `bedrock-agentcore:us-east-1:609617804976:gateway/northstar-assist-gateway-hd1uvsa8f3` | The Northstar gateway | allowed |
| HARNESS | `bedrock-agentcore:InvokeGateway` | `bedrock-agentcore:us-east-1:609617804976:gateway/other-gateway-abc123` | Any other gateway | implicitDeny |
| HARNESS | `bedrock:Retrieve` | `bedrock:us-east-1:609617804976:knowledge-base/WUWHZC06MP` | Direct KB retrieval, bypassing the gateway | implicitDeny |
| HARNESS | `bedrock-agentcore:StartBrowserSession` | `bedrock-agentcore:us-east-1:aws:browser/aws.browser.v1` | Browser tool (not configured) | implicitDeny |
| HARNESS | `bedrock-agentcore:InvokeCodeInterpreter` | `bedrock-agentcore:us-east-1:aws:code-interpreter/aws.codeinterpreter.v1` | Code Interpreter (not configured) | implicitDeny |
| HARNESS | `bedrock-agentcore:RetrieveMemoryRecords` | `bedrock-agentcore:us-east-1:609617804976:memory/NorthstarAssist-abc` | Memory (disabled) | implicitDeny |
| HARNESS | `elasticfilesystem:ClientWrite` | `elasticfilesystem:us-east-1:609617804976:file-system/fs-12345678` | EFS mounts (not configured) | implicitDeny |
| HARNESS | `bedrock-mantle:CreateInference` | `bedrock-mantle:us-east-1:609617804976:project/default` | Bedrock Mantle API (not used) | implicitDeny |
| HARNESS | `s3:GetObject` | `s3:::northstar-assist-kb-5ca661ad/csv/employee_directory.csv` | Direct read of the source documents | implicitDeny |
| HARNESS | `logs:CreateLogGroup` | `logs:us-east-1:609617804976:log-group:/aws/bedrock-agentcore/runtimes/harness_NorthstarAssist-92Prr07JAK-DEFAULT` | Its own runtime log group | allowed |
| HARNESS | `logs:CreateLogGroup` | `logs:us-east-1:609617804976:log-group:/aws/bedrock-agentcore/runtimes/other-runtime-DEFAULT` | Another runtime's log group | implicitDeny |
| GATEWAY | `bedrock:Retrieve` | `bedrock:us-east-1:609617804976:knowledge-base/WUWHZC06MP` | The Northstar knowledge base | allowed |
| GATEWAY | `bedrock:GetKnowledgeBase` | `bedrock:us-east-1:609617804976:knowledge-base/WUWHZC06MP` | The Northstar knowledge base | allowed |
| GATEWAY | `bedrock:Retrieve` | `bedrock:us-east-1:609617804976:knowledge-base/OTHERKB123` | Any other knowledge base | implicitDeny |
| GATEWAY | `bedrock:AgenticRetrieveStream` | `*` | Agentic retrieval (not configured; the action has no resource-level permissions) | implicitDeny |
| GATEWAY | `bedrock:InvokeModel` | `bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0` | Model invocation by the gateway | implicitDeny |
| GATEWAY | `bedrock:Rerank` | `*` | Reranking (not configured) | implicitDeny |
| GATEWAY | `bedrock:ApplyGuardrail` | `bedrock:us-east-1:609617804976:guardrail/753a9dgwqe2f` | Guardrails are applied by the harness, not the gateway | implicitDeny |
| GATEWAY | `s3:GetObject` | `s3:::northstar-assist-kb-5ca661ad/csv/employee_directory.csv` | Direct read of the source documents | implicitDeny |
| KB | `bedrock:InvokeModel` | `bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0` | The embedding model | allowed |
| KB | `bedrock:InvokeModel` | `bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0` | A generation model | implicitDeny |
| KB | `s3:GetObject` | `s3:::northstar-assist-kb-5ca661ad/html/company_policies_handbook.html` | Reading the document bucket | allowed |
| KB | `s3:PutObject` | `s3:::northstar-assist-kb-5ca661ad/html/company_policies_handbook.html` | Writing to the document bucket | implicitDeny |
| KB | `aws-marketplace:Subscribe` | `*` | Marketplace subscriptions (not needed for Titan) | explicitDeny |
