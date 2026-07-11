# agent-runtime Specification Delta

## ADDED Requirements

### Requirement: Workers Publish Artifact References And Events

Agent workers SHALL register produced artifacts with the shared local artifact
registry and return bounded references plus canonical artifact events. They
SHALL NOT embed binary content, arbitrary layout markup, or unrestricted local
paths in chat/session responses.

#### Scenario: Research worker finds images

- **WHEN** a worker finds candidate images while researching a user request
- **THEN** it SHALL submit source-linked media candidates to the safe fetcher,
  publish pending/ready/failed events, and reference the resulting artifact ids

#### Scenario: Layout validation fails

- **WHEN** a worker-generated canvas fails schema validation
- **THEN** the worker result SHALL retain its full text and sources, mark the
  canvas artifact failed, and SHALL NOT fail the entire assistant turn

### Requirement: Artifact Events Preserve Session And Cancellation Boundaries

Artifact production SHALL remain bound to the originating session and task.
Speech cancellation SHALL NOT cancel artifact generation; explicit task cancel
MAY cancel pending fetch/layout work and SHALL emit terminal artifact states.

#### Scenario: User interrupts spoken summary

- **WHEN** the user barges in while a typhoon canvas is still receiving images
- **THEN** speech SHALL stop while permitted artifact work continues and its
  progress remains visible in the session
