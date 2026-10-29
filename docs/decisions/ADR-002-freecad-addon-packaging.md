# ADR-002: Modern FreeCAD addon within the monorepo

- Status: Accepted for Phase 1 implementation; public distribution deferred
- Date: 2026-10-29

## Decision

Keep the client in `clients/freecad`, with `freecad.forgepdm` as an implicit
namespace child and `init_gui.py` as the only GUI entry point. Preserve all nine
public command IDs and existing document metadata. Delay command/Qt imports
until Workbench initialization; importing the base package needs neither FreeCAD
nor the ForgePDM backend. Keep the HTTP client standard-library-only.

Build a deterministic ZIP containing the addon root metadata, client modules,
resources and user documentation. Exclude backend code, development tools,
tests, caches, databases and legacy references through an explicit allowlist.
Keep ordinary Python packaging metadata separate from the backend project.
The ZIP is the supported Phase 1 artifact; wheel publication is not required.
Do not create an external repository or publish artifacts in this phase.

Use the official template's manifest namespace. Validate offline using the pinned
official v1.0 schema with an explicit XSD chameleon-include namespace binding and local
invariant checks. `clients/freecad/tools/vendor/README.md` records the upstream
conflict, license, provenance and exact adaptation. Actual FreeCAD parsing is a
separate manual acceptance gate, never inferred from schema or mocked tests.

## Consequences

- Users replace the old installation rather than installing two loader trees.
- `ForgePDM.*` imports used by the old loader are replaced with relative imports;
  no document metadata or backend endpoint changes are needed.
- An isolated addon has no backend runtime dependencies. Development-only
  lxml/pytest/ruff stay outside the FreeCAD interpreter.
- Initial declared target is FreeCAD 1.0+ with Python 3.11+; real OS/Qt/runtime
  support remains unverified until the documented GUI checklist is executed.
- Original icons and English translation hooks are included. No translated
  strings or third-party template assets are represented as reviewed output.
- Existing code has no selected project license. Record UNLICENSED rather than
  inventing a grant. Owner-approved licensing and maintainer contact information
  are prerequisites for public catalog submission.
- The manifest repository URL identifies the monorepo source; it is not a claim
  that Addon Manager can install its nested addon directory from that URL.
  An addon-only distribution branch or another approved mechanism remains a
  Phase 7 decision.

## Deferred

Asynchronous HTTP, search, workspace management, assembly reference recovery,
BOM extraction and changes to authoritative PDM rules remain later phases.
