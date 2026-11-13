// Persist only revision intent. Credentials and bearer tokens remain in memory.
export async function createRevision(api, itemId, sourceId, askNote, storage = globalThis.localStorage) {
  const actor = (await api.request('/auth/me')).id;
  const key = `forgepdm.revision.v1:${actor}:${itemId}:${sourceId}`;
  const execute = async () => {
    let operation = JSON.parse(storage.getItem(key) || 'null');
    if (operation && (operation.actor !== actor || operation.item !== itemId || operation.source !== sourceId || !operation.operation_id || typeof operation.change_note !== 'string')) {
      throw new Error('The revision recovery record needs inspection; it has been preserved.');
    }
    if (!operation) {
      const note = askNote();
      if (!note?.trim()) return null;
      operation = {actor, item: itemId, source: sourceId, operation_id: crypto.randomUUID(), change_note: note.trim()};
      storage.setItem(key, JSON.stringify(operation));
    }
    try {
      return await api.request(`/items/${itemId}/revision-operations/${operation.operation_id}`);
    } catch (error) {
      if (error.status !== 404) throw error;
    }
    return api.request(`/items/${itemId}/revisions/recoverable`, {method:'POST', body:{
      operation_id: operation.operation_id, expected_source_revision_id: sourceId, change_note: operation.change_note
    }});
  };
  return globalThis.navigator?.locks ? navigator.locks.request(key, execute) : execute();
}
