### Requirement ID

FR-KIO2-05

### Title

AI Fault Localization  to train from replayed traces and slice context

### Objective (Purpose)

Uses machine learning to help detect anomalies in sets of execution traces. These anomalies are statistical hints of potential bugs that can be used to guide the developer upon debugging a given issue. 

### Description (Scope)


### Owner (Partner)

HESSO

### Contributors (Partner)


### Priority

High

### Constraints / Assumptions


### Acceptance Criteria


### Dependency (Relationship)


### Pre-Condition(s)

The notion of distance between traces is formally defined. 

The evaluation of trace distances is implemented. 

The replay engine is implemented and it support interactions with multiple execution traces simultaneously. 

### Input

A set of execution traces relating to a single program ran with the different inputs and configurations, and the source files corresponding to this program. 

### Invariants

Anomalies are defined as statistical deviations in the assigned values across a set of traces derived from the same program. 

### Behaviour and Sequences

Build an infrastructure to train and perform inference of anomaly detection models on a set of execution traces derived from the same program. 

### Output

A list of statistical anomalies associated with a score, in the form of a log-likelihood.  

### Post–Condition(s)

Each statement in a trace is associated with an anomaly score. 

### Project Assignment

- [ ] ✅ I confirm this requirement will be linked to a GitHub Project manually during creation.