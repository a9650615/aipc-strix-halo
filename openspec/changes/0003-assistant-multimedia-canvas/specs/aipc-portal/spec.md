# aipc-portal Specification Delta

## ADDED Requirements

### Requirement: Portal Renders Assistant Artifact Surfaces

The Portal SHALL provide artifact list, preview, and detail surfaces backed by
the localhost artifact API. Artifact cards SHALL be separate from service-
health metadata cards and SHALL render only validated artifact/canvas schemas
using trusted components.

#### Scenario: Typhoon canvas opens in Portal

- **WHEN** a ready typhoon canvas artifact is opened
- **THEN** Portal SHALL render its summary, source/update badge, safe imagery,
  track/timeline, and text fallback without loading original remote URLs

#### Scenario: Unknown canvas component

- **WHEN** Portal receives a canvas containing an unknown component/property
- **THEN** it SHALL reject that revision and show the last valid snapshot or
  deterministic text fallback

### Requirement: Portal Canvas Is Responsive And Accessible

The Portal renderer SHALL provide keyboard-accessible actions, alt text,
source labels, readable responsive degradation, reserved media aspect ratios,
and fixed design tokens. It SHALL NOT evaluate agent strings as markup or code.

#### Scenario: Narrow display

- **WHEN** a grid/gallery/map-rich canvas is displayed at narrow width
- **THEN** Portal SHALL collapse it into a readable single-column layout while
  preserving source, freshness, alt text, and open-artifact functionality
