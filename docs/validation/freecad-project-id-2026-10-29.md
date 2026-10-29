# Project ID validation regression — 2026-10-29

## Problem and change

Entering a project number into the UUID field produced an unformatted FastAPI
validation list containing `type`, `loc`, `input` and `ctx`. The addon now
distinguishes the project's internal ID from its number in the prompt, validates
UUID syntax locally before creating the Item and handles dialog cancellation.
Server validation failures are converted into readable field messages; string
permission errors and HTTP status codes remain available. Request endpoints,
payload fields and authoritative backend authorization are unchanged.

## Actual validation

- Addon suite: **43 tests passed in 0.59 seconds**. This includes the earlier
  read-only save tests and eight additional project/error-display cases.
- Ruff lint and formatting passed; manifest validation and ZIP build passed.
- The installed addon was reloaded in FreeCAD **1.1.4**, Python **3.11.14**,
  Qt **6.8.3**, Linux, through FreeCAD MCP Bridge.
- Four live checks passed: malformed local ID guidance, valid UUID acceptance,
  readable formatting of a real backend HTTP 422 response, and preservation of
  the user's documents and authenticated identity. The deliberately invalid
  creation request was rejected by the server and created no Item.
- At the user's explicit selection, the local `alice` account was granted editor
  membership in the existing Prototype Project using the administration CLI.
  Its global role remains unchanged.

The server still requires a project UUID; a project picker or project-number
lookup has not been implemented. This is a focused usability fix, not Phase 2.
