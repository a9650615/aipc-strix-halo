# AIPC Control Center SPA Design

This design is implemented by OpenSpec change
`0004-aipc-control-center-spa`. It adopts the public control-center patterns
of quick system blocks, a device detail surface, and an immediate physical
button path without copying ASUS implementation or assets.

Astro builds the SPA; the existing Python portal remains the localhost runtime
and authoritative backend. The existing status dashboard is migrated as a
snapshot provider, not retained as a second user interface. Z13 Flow chassis
I/O and AI MAX+ 395 telemetry are separate data domains, composed in one Home
view and split in Device versus AI & Voice views.

The first release has no configurable button policy. It preserves the current
button action while publishing observed state to the portal, then hardware
verification decides whether changing the action is warranted.
