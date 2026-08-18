### Requirement ID

FR-KIO2-04

### Title

Post-mortem expression evaluator 

### Objective (Purpose)

Enables the (partial) reuse of the original source code during post-mortem interactive debugging; expressions requiring data not recorded in the trace query data from mocks. 

Enables the speculative exploration of data and behaviors not that were not captured in the execution traces, starting from arbitrary program points. 

### Description (Scope)

The system shall build dynamic dependence graphs (data and control) from replayed traces to compute minimal backward/forward slices and rank dependencies by causal impact.

### Owner (Partner)

HESSO

### Contributors (Partner)


### Priority

High

### Constraints / Assumptions

### Acceptance Criteria

### Dependency (Relationship)

### Pre-Condition(s)

The replay engine is implemented and available. 

### Input

An execution trace and the corresponding source files of the program from which it has been generated. 

Mocks for services that could have interacted with the program under test. 

### Invariants

An expression successfully evaluated during post-mortem debugging produces a result equivalent (for some notion of equivalence) to that of the same expression evaluated during live execution if and only if: 

All its dependencies were captured in the execution trace; or 

Mocks reproduce behavior equivalent (for some notion of equivalence) to that of the services that were available during live execution. 

### Behaviour and Sequences

Implement the infrastructure supporting the instantiation of a Python interpreter, the configuration of its state (locals and globals), and the injection of mocked dependencies. 

Implement UI for the live debugging of arbitrary expressions evaluated in the context of a specific recorded state. 

### Output


### Post–Condition(s)


### Project Assignment

- [ ] ✅ I confirm this requirement will be linked to a GitHub Project manually during creation.