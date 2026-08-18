### Requirement ID

FR-KIO2-08

### Title

LLM – Assisted Debugging

### Objective (Purpose)

To provide initial human-in-the-loop guidance for live GDB sessions by suggesting breakpoint strategies, process/thread inspections, and fix hypotheses to improve developer productivity for junior-mid developers, while requiring explicit user approval for all debugger actions.

### Description (Scope)

The LLM acts as an intelligent assistant during live GDB sessions, ingesting real-time data like thread snapshots, stack traces, and lock info. It surfaces targeted, advisory suggestions (e.g., where to set breakpoints, which threads to inspect, potential concurrency pattern failures) via the KIO1 orchestration HUD. Engineers must explicitly approve or reject each recommendation before the debugger executes any action, ensuring safety and accountability. This near-term, HITL approach is based on the rationale that full autonomous debugger control is not yet practical.

Rationale:

**Feasible near term:** Requiring human approval eliminates the need for fully automated debugger control, shrinking integration risk while still showcasing value. 

**Improved insight:** LLM-generated hypotheses accelerate root cause analysis for deadlocks, races, and starvation by synthesizing runtime evidence, code context, and prior fixes. 

**Guardrails:** HITL gating ensures debugger state changes stay auditable and prevents unintended process corruption. 

**Traceability:** Every suggestion, approval, and outcome feeds the shared memory/logging layer, strengthening reproducibility and future automation potential. 

### Owner (Partner)

AI4

### Contributors (Partner)

UREAD

### Priority

Medium

### Constraints / Assumptions

- Safety/Execution: The LLM never executes a debugger command without explicit human approval; it provides suggestions only (Invariants).
- Traceability: Every suggestion, approval, and resulting GDB action is logged with timestamp, context snapshot, and policy version (Invariants).
- Integration: Full automation is not assumed, matching current capabilities (no direct debugger hooks). The MVP emphasizes structured telemetry, reproducible HITL approvals, and iterative reasoning.

### Acceptance Criteria

- Advisory UI panels (HITL-facing) are delivered and functional.
- MCP connectors and agent adapters successfully stream GDB transcripts into the LLM helper and return accepted actions back to engineers.
- Structured session logs (including LLM reasoning, human approvals, and executed commands) are generated and auditable.
- The LLM successfully generates a breakpoint or inspection strategy suggestion based on GDB telemetry in a live session.

### Dependency (Relationship)

- All FR-KIO1

### Pre-Condition(s)

1. LM engine must be live so KIO1 can run debugger-specific prompts, tool calls, and guardrails. (KIO 1 Requirement)  
2. Logging/observability from FR-KIO1 (Monitoring and Logging / Audit)  ensures debugger suggestions and approvals remain auditable for safety. 
3. Workflow Orchestration shall be ready by KIO1.   
4. Agent memory needs to exist to store thread snapshots, breakpoint rationales, and HITL decisions for iterative debugging- KIO1 Requirement.  

### Input

- Source and build metadata: file paths, symbols, compiler flags, known synchronization primitives to map stack frames back to code context.  
- Human prompts/feedback: natural-language questions (“why is thread 7 blocked?”), approvals/rejections of suggested actions, manual notes on suspected races.
- Policy/guardrail settings: allowed debugger commands, 
- Stuff from the GDB: *  Thread lists, bt/thread apply all bt output, lock ownership, watchpoint hits, register/memory snapshots 

### Invariants

- The LLM never executes a debugger command without explicit human approval; suggestions only. 
- Traceability: Every recommendation, approval, and resulting GDB action is logged with timestamp, context snapshot, and policy version. 

### Behaviour and Sequences

- PHASE 1: FR-KIO1-10 targets the same human-in-the-loop workflow Cursor supports today: engineers run GDB manually, paste thread/stack output into the IDE, and the Claude-backed assistant suggests what to inspect next. The requirement formalizes that pattern for KIO1—LLM guidance remains advisory, while humans execute debugger commands. Full automation isn’t assumed, matching current Cursor capabilities (no direct debugger hooks). Instead, the MVP emphasizes structured telemetry capture, reproducible HITL approvals, and iterative reasoning loops inside the IDE. 

- PHASE 2:  The orchestrator uses policy-grounded prompts to reason over live GDB telemetry, stored context, and workflow state, then produces debugger recommendations that stay HITL-gated. MCP adapters keep Cursor as the human console: transcripts flow from GDB into the agent layer, while accepted suggestions flow back for execution. Every step is logged with guardrails, so multithread diagnoses remain reproducible and auditable 

- [OPTIONAL] PHASE 3: 

https://www.distillabs.ai/blog/vibe-tuning-the-art-of-fine-tuning-small-language-models-with-a-prompt
https://arxiv.org/abs/2506.02153 

### Output

- Approved debugger guidance 
- Structured session logs (Cursor/MCP context, LLM prompts/responses, human approvals) 

Deliverables: 

1. HITL-facing advisory UI panels 
2. MCP connectors and agent adapters that stream debugger transcripts into the LLM helper and return actions back to engineers. 

### Post–Condition(s)

- Reproducable record.  LLM reasoming, human choices., executed commands , and resolution status. 
- Guardrails verified with human approval 
- Shared memory updated with lessons learned

### Project Assignment

- [ ] ✅ I confirm this requirement will be linked to a GitHub Project manually during creation.