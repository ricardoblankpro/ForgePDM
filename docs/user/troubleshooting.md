# Troubleshooting

Preserve open edits and exact snapshot pins while diagnosing a failure. Report
the command, item/revision, addon/backend versions, runtime and full error text;
keep passwords and tokens out of reports. See [test and issue guidance](../../CONTRIBUTING.md).

| Symptom | Check or recovery |
|---|---|
| Cannot connect or sign in | Confirm server URL and `/health`, account state and request timeout. Reset local passwords with the administrator CLI if needed. |
| Addon loads twice or fails after an upgrade | Verify one `Mod/ForgePDM` installation with the namespaced loader; replace stale addon files rather than overlaying installations. |
| Open is unavailable | Choose a revision with an uploaded native CAD snapshot. Historical selections do not fall back to another upload. |
| Workspace is rejected | Choose an existing writable local root for the same server/account. Keep its complete ledgers/cache and avoid unsupported network storage. |
| Edit or drawing update is rejected | Use a managed Working copy with your live checkout; finish active CAD edit mode. Released revisions require a new revision. |
| CAD-to-BOM preparation reports unsaved changes | Save/upload the changed managed component and parent. Genuine dirty documents remain protected; acquiring checkout does not discard their edits. |
| A reviewed proposal became stale | Reload/review current server evidence. Changed leases, snapshots or permissions invalidate the proposal; do not blindly retry a write. |
| Mass is unavailable | Inspect the source/reason: missing material density, changed assignment, missing S mass or unresolved subassembly BOM. Unknown is not zero. |
| Flattened drawing is blocked | Complete stored BOMs for empty subassemblies, then refresh. A partial structure cannot generate a complete flattened drawing. |
| Existing drawing still has an old title/footer or quantities | Explicitly update the table through Drawing BOM. Loading an old snapshot preserves frozen contents. |
| Upload/check-in/revision/PDF response was lost | Retry the same command to recover its durable operation. Preserve local journals and newer edits; inspect server state before starting another intent. |

A read-only `forgepdm recovery-report` checks database/blob integrity and identifies
incomplete/unreferenced candidates. It never deletes data. Use the [operations
guide](../operations/server.md#recovery) for an authoritative offline review and
matching database/blob restoration.
