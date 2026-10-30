# ADR-003: Responsive FreeCAD workflows and authorized catalog reads

- Status: Accepted within the approved Phase 2 scope
- Date: 2026-10-29

## Decision

Keep the modular monolith, SQLite schema and existing editing endpoints intact.
Add a read-only application catalog service and versioned API reads for project
selection, item search and explicit revision retrieval. Filter permissions in
SQL before pagination. Use existing project memberships and global admin rules;
do not make the client authoritative for access or lifecycle decisions.

Represent each existing client command as a GUI-thread generator that yields
explicit HTTP/transfer requests. A single active workflow owns a standard-library
ThreadPoolExecutor with one worker. A GUI-owned QTimer polls completed futures
and resumes the generator. Worker code receives only the client and ordinary
data; document/widget operations remain on the GUI thread. Guard polling against
reentry because Qt dialogs can start nested event loops.

Keep the engine independent of Qt for concurrency/failure tests. The Qt adapter
owns progress, cancellation, diagnostics and the busy state. Preserve all nine
public command IDs. HTTP has finite, user-configurable timeouts; transfer chunks
check cooperative cancellation. Do not terminate threads or automatically retry
mutations. Short finalization requests disable cancellation; canceling an upload
stops subsequent check-in, but cannot undo a server-side commit or guarantee that
the server did not receive the complete file. Explain uncertain outcomes.

Remember only server URL, username and timeout through FreeCAD parameters.
Passwords and tokens remain in memory. Clear expired/revoked sessions locally;
explicit logout runs over HTTP in a worker. Add human-readable project/item/
revision selection, including pagination, rather than requesting internal UUIDs.

## API additions

- `GET /api/v1/projects?editable=true&limit=50&offset=0`
- `GET /api/v1/items?q=bracket&limit=50&offset=0`
- `GET /api/v1/items/{item_id}/revisions?limit=50&offset=0`
- `GET /api/v1/revisions/{revision_id}`

Paged reads return `items`, `limit`, `offset`, and `has_more`. Limit is 1–100;
offset is non-negative. Projects expose number, name, ID and `can_edit` and
exclude archived projects. Item search matches literal substrings in number,
name and description, using SQLite's existing ASCII case folding. Revision reads
bind explicit IDs; history is ordered by descending sequence. Inaccessible item
history/revision lookups return 404. No migration is needed.

## Limits and alternatives

A Qt signal/QThread design is also valid. Timer-polled futures keep the transport
and engine testable without Qt, at the cost of a small polling interval and an
explicit busy/cancellation lifecycle. This is a local client implementation
choice, not a replacement backend architecture.

One operation at a time avoids concurrent session/document command races.
Cancellation may wait for a blocking socket call to finish or reach its timeout.
CAD save/recompute remains synchronous on the GUI thread. Network responsiveness
does not establish file snapshot, reference integrity or atomic check-in; those
remain Phases 3–5. Downloads publish staged files without replacing an existing
destination via a same-directory hard link; filesystems must support this
operation or retrieval reports failure without overwriting existing content.

No web UI, SSO, credential persistence, PostgreSQL migration, assembly-reference
rewriting, BOM extraction or public distribution is introduced here.

## References

- [Qt timer affinity](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QTimer.html)
- [Python futures](https://docs.python.org/3.11/library/concurrent.futures.html)
- [Qt progress dialogs](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QProgressDialog.html)
