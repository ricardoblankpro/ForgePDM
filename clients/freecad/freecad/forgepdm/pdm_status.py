"""GUI-independent ephemeral status reads and presentation rules."""

from datetime import datetime, timezone
from html import escape

from . import workspace

COLORS = {
    "mine": "#2878c8",
    "other": "#c46b14",
    "released": "#328449",
    "revision": "#9256c7",
    "snapshot": "#13878c",
    "local": "#b65c22",
    "unknown": "#7a7f87",
}


def fetch(client, targets, hash_cache):
    """Only plain captured records cross into this worker; no CAD/Qt imports."""
    local = {}
    language = getattr(client, "description_language", None)
    for target in targets:
        client._checkpoint()
        key = target["key"]
        value = {"dirty": target["dirty"], "pin": None, "problem": "Snapshot unknown"}
        try:
            binding = workspace.binding(target["path"], client.base_url, require_uploaded=False)
            entry = binding["entry"]
            if (entry.get("item_id"), entry.get("revision_id")) != (
                target["item_id"],
                target["revision_id"],
            ):
                raise workspace.WorkspaceError(
                    "Local identity is not bound to an uploaded snapshot"
                )
            if (
                not entry.get("dataset_id")
                or not entry.get("file_id")
                or not entry.get("working_hash")
            ):
                raise workspace.WorkspaceError("Local snapshot has not been uploaded")
            path = workspace._safe_path(binding["directory"], entry["path"])
            stat = path.stat()
            stamp = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            digest = hash_cache.get(stamp)
            if digest is None:
                digest = workspace.digest(path, client._checkpoint)[0]
                hash_cache[stamp] = digest
            value["pin"] = (entry["dataset_id"], entry["file_id"])
            value["dirty"] |= digest != entry["working_hash"]
            value["problem"] = None
        except (workspace.WorkspaceError, OSError, ValueError, KeyError, TypeError):
            # Keep status useful for a managed revision even when local pins are unavailable.
            pass
        local[key] = value
    identifiers = list(
        dict.fromkeys(
            revision
            for target in targets
            for revision in [target["revision_id"]]
            + [
                entry["revision_id"]
                for entry in target.get("fasteners", {}).values()
                if entry.get("revision_id")
            ]
        )
    )
    remote, checked_at = {}, None
    for start in range(0, len(identifiers), 200):
        client._checkpoint()
        batch = identifiers[start : start + 200]
        response = (
            client.revision_status(batch, language=language)
            if language
            else client.revision_status(batch)
        )
        checked_at = response["checked_at"]
        remote.update({row["revision_id"]: row for row in response["items"]})
    # A bounded cache avoids retaining old document paths indefinitely.
    if len(hash_cache) > 4096:
        hash_cache.clear()
    return dict(local=local, remote=remote, checked_at=checked_at, language=language)


def description_text(target, snapshot, language, fastener=None):
    """Display text only: preserve local source edits and exact occurrence revisions."""
    snapshot = snapshot or {}
    remote = snapshot.get("remote", {}).get((fastener or target).get("revision_id"), {})
    text = target.get("description")
    if fastener is not None:
        text = fastener["description"]
        if remote.get("available"):
            text = remote.get("description", text)
    elif remote.get("available") and (
        text is None
        or not target.get("dirty")
        and target.get("description_token") != remote.get("description_token")
    ):
        text = remote.get("description", text)
    localized = remote.get("localized_description")
    if (
        language
        and snapshot.get("language") == language
        and remote.get("available")
        and localized
        and localized.get("original_text") == text
    ):
        text = localized["text"]
    return text or ""


def describe(remote, local, checked_at, *, now=None, stale=None):
    now = now or datetime.now(timezone.utc)
    badges, details = [], []

    def add(kind, text):
        badges.append(dict(kind=kind, text=text, color=COLORS[kind]))

    if not remote or not remote.get("available"):
        add("unknown", "Status unavailable")
        details.append("Missing, inaccessible, or not yet checked on this server.")
    else:
        details.append("{} — revision {}".format(remote["item_number"], remote["revision_label"]))
        lifecycle = remote["lifecycle_state"]
        details.append("Lifecycle: " + lifecycle.title())
        checkout = remote.get("checkout")
        if checkout and datetime.fromisoformat(checkout["expires_at"]) > now:
            owner = checkout["display_name"] or checkout["username"]
            add("mine" if checkout["is_mine"] else "other", "You" if checkout["is_mine"] else owner)
            details.append("Checked out by {} until {}".format(owner, checkout["expires_at"]))
        else:
            details.append("No active checkout at the last server check.")
        if lifecycle == "released":
            add("released", "Released")
        elif lifecycle != "working":
            add("unknown", lifecycle.title())
        newer = remote.get("newer_revision")
        if newer:
            add("revision", "Rev {} available".format(newer["label"]))
            details.append(
                "Newer revision available: " + newer["label"] + ". Explicit replacement required."
            )
        latest = remote.get("latest_snapshot")
        pin = (local or {}).get("pin")
        if not pin:
            add("unknown", "Snapshot unknown")
        elif latest and pin != (latest["dataset_id"], latest["file_id"]):
            add("snapshot", "Snapshot update")
            details.append(
                "A newer upload of this same revision is available. Existing pins are preserved."
            )
        if pin:
            details.append("Local pin: {}/{}".format(*pin))
        if latest:
            details.append(
                "Latest server snapshot: {}/{} — {}".format(
                    latest["dataset_id"], latest["file_id"], latest["created_at"]
                )
            )
        else:
            details.append("No native snapshot uploaded on this revision.")
        if (local or {}).get("dirty"):
            add("local", "Local edits")
            details.append("Local changes are not included in the recorded uploaded snapshot.")
        if not badges:
            add("unknown", "Working · current" if latest and pin else "Working")
    if checked_at:
        details.append("Last server check: " + checked_at)
    if stale:
        badges = [dict(kind="unknown", text="Stale status", color=COLORS["unknown"])]
        details.insert(0, "STALE — last known information only. " + stale)
    details.append(
        "Status is informational. Editing commands recheck permissions and checkout ownership."
    )
    return dict(
        text=" · ".join(b["text"] for b in badges),
        badges=badges,
        tooltip="<b>ForgePDM</b><br>" + "<br>".join(escape(line) for line in details),
    )
