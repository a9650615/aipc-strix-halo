# voice-streaming Specification Delta

## ADDED Requirements

### Requirement: Voice Surfaces Announce And Preview Artifacts

Voice responses SHALL speak the canvas `spoken_text` and MAY expose bounded
artifact metadata (`artifact_id`, kind, title, preview availability, local open
action) to the overlay. They SHALL NOT place binary media or full canvas JSON in
the voice status file.

#### Scenario: Voice asks for typhoon status

- **WHEN** the result contains a visual typhoon canvas
- **THEN** the assistant SHALL speak the concise status, show at most the compact
  allowed preview, and offer to open the full Portal artifact without opening it
  automatically

#### Scenario: Overlay cannot render preview

- **WHEN** the overlay lacks multimedia support or the preview fails
- **THEN** it SHALL show title, text fallback, and an open-in-Portal action while
  voice completion remains successful
