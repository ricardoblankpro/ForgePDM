"""Small standard-library HTTP client for the ForgePDM API."""

import hashlib
import http.client
import json
import os
import re
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import local


class ForgePDMError(Exception):
    def __init__(self, message, status=None, code="request_failed"):
        Exception.__init__(self, message)
        self.status = status
        self.code = code


def _error_message(detail, status):
    """Present API validation messages without exposing raw response structures."""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        messages = []
        for issue in detail:
            if not isinstance(issue, dict):
                continue
            location = issue.get("loc") or []
            field = next((part for part in reversed(location) if isinstance(part, str)), "")
            if field == "project_id" and str(issue.get("type", "")).startswith("uuid"):
                message = (
                    "Project: enter the project's ID (UUID), not its project number. "
                    "Ask your administrator for the ID of a project you can access."
                )
            else:
                label = field.replace("_", " ").capitalize()
                text = issue.get("msg")
                if not isinstance(text, str):
                    continue
                message = "{}: {}".format(label, text) if label else text
            if message not in messages:
                messages.append(message)
        if messages:
            return "Please check your input:\n" + "\n".join(messages)
    return "ForgePDM request failed (HTTP {}).".format(status)


class ForgePDMClient:
    """API client with a memory-only bearer token and streamed file transfer."""

    def __init__(self, base_url, timeout=60):
        self.base_url = base_url.strip().rstrip("/")
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("Server URL must start with http:// or https://")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Server URL must not include credentials, a query, or a fragment")
        if not 1 <= float(timeout) <= 300:
            raise ValueError("Connection timeout must be between 1 and 300 seconds")
        self._parsed = parsed
        self.timeout = timeout
        self.token = None
        self.expires_at = None
        self._local = local()

    @contextmanager
    def operation(self, context):
        self._local.context = context
        try:
            yield
        finally:
            self._local.context = None

    def _checkpoint(self, completed=None, total=0):
        context = getattr(self._local, "context", None)
        if context is not None:
            context.check()
            if completed is not None:
                context.progress(completed, total)

    def is_expired(self):
        if not self.expires_at:
            return False
        return datetime.fromisoformat(self.expires_at).astimezone(timezone.utc) <= datetime.now(
            timezone.utc
        )

    def login(self, username, password):
        result = self._json_request(
            "POST",
            "/api/v1/auth/login",
            {"username": username, "password": password},
            authenticated=False,
        )
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("access_token"), str)
            or not result["access_token"]
            or not isinstance(result.get("user"), dict)
        ):
            raise ForgePDMError(
                "ForgePDM returned an invalid login response.", code="invalid_response"
            )
        expiry = result.get("expires_at")
        if expiry is not None:
            try:
                parsed_expiry = datetime.fromisoformat(expiry)
                if parsed_expiry.tzinfo is None:
                    raise ValueError("missing time zone")
            except (ValueError, TypeError):
                raise ForgePDMError(
                    "ForgePDM returned an invalid session expiry.", code="invalid_response"
                )
        self.token = result["access_token"]
        self.expires_at = expiry
        return result["user"]

    def logout(self):
        if self.token:
            try:
                self._json_request("POST", "/api/v1/auth/logout", None)
            finally:
                self.token = None
                self.expires_at = None

    def list_projects(self, editable=False, limit=50, offset=0):
        query = urllib.parse.urlencode(
            {"editable": str(editable).lower(), "limit": limit, "offset": offset}
        )
        return self._catalog_request("/api/v1/projects?" + query)

    def search_items(self, query="", limit=50, offset=0, number_series=None):
        params = {"q": query, "limit": limit, "offset": offset}
        if number_series:
            params["number_series"] = number_series
        query = urllib.parse.urlencode(params)
        return self._catalog_request("/api/v1/items?" + query)

    def list_revisions(self, item_id, limit=50, offset=0):
        query = urllib.parse.urlencode({"limit": limit, "offset": offset})
        return self._catalog_request(
            "/api/v1/items/" + self._quote(item_id) + "/revisions?" + query
        )

    def get_revision(self, revision_id):
        return self._json_request("GET", "/api/v1/revisions/" + self._quote(revision_id))

    def revision_status(self, revision_ids):
        try:
            return self._json_request(
                "POST", "/api/v1/status/revisions", {"revision_ids": revision_ids}
            )
        except ForgePDMError as error:
            if error.status == 404:
                raise ForgePDMError(
                    "Tree status requires an updated ForgePDM backend. Restart/update the server.",
                    404,
                    "unsupported_server",
                ) from error
            raise

    def fetch_tree_status(self, targets, hash_cache):
        from . import pdm_status

        return pdm_status.fetch(self, targets, hash_cache)

    def inspect_server_update(self, path, item_id, revision_id):
        from . import server_updates

        return server_updates.inspect(self, path, item_id, revision_id)

    def update_baseline(self, path, item_id, revision_id):
        from . import server_updates

        return server_updates.baseline(self, path, item_id, revision_id)

    def prepare_component_update(self, path, item_id, revision_id, references):
        from . import server_updates

        return server_updates.prepare_components(self, path, item_id, revision_id, references)

    def component_update_baseline(self, path, item_id, revision_id, references):
        from . import server_updates

        return {
            "baseline": server_updates.baseline(self, path, item_id, revision_id),
            "pins": self.validate_references(references),
        }

    def get_manifest(self, dataset_id):
        try:
            return self._json_request(
                "GET", "/api/v1/datasets/" + self._quote(dataset_id) + "/manifest"
            )
        except ForgePDMError as error:
            if error.status == 404 and str(error) == "dataset reference manifest not found":
                return None
            if error.status == 404 and str(error) == "Not Found":
                raise ForgePDMError(
                    "This server needs the Phase 3 dataset-reference API. Update/restart the backend.",
                    404,
                    "unsupported_server",
                ) from error
            raise

    def attach_manifest(self, dataset_id, source_file_id, references):
        return self._json_request(
            "POST",
            "/api/v1/datasets/" + self._quote(dataset_id) + "/manifest",
            {
                "source_file_id": source_file_id,
                "profile": "freecad-fasteners-v1"
                if any(r["property_name"] == "BaseObject" for r in references)
                else "freecad-app-link-v1",
                "references": references,
            },
        )

    def prepare_working(self, root):
        from .workspace import prepare_working

        return prepare_working(self.base_url, root)

    def copy_revision_source(self, source, destination, references):
        from .workspace import copy_revision_source

        return copy_revision_source(source, destination, references, self._checkpoint)

    def newer_revisions(self, item_id, source_revision_id):
        source = self.get_revision(source_revision_id)
        if source["item_id"] != item_id:
            raise ValueError("Component revision does not belong to the selected item")
        revisions, offset = [], 0
        while True:
            self._checkpoint()
            page = self.list_revisions(item_id, limit=100, offset=offset)
            revisions.extend(
                row
                for row in page["items"]
                if row["sequence"] > source["sequence"] and row["lifecycle_state"] != "obsolete"
            )
            if not page["has_more"]:
                return revisions
            offset += 100

    def bom_revision_updates(self, lines):
        """Report newer revisions without changing any stored or CAD references."""
        items, updates, pending = {}, {}, list(lines)
        while pending:
            line = pending.pop()
            item_id = line["item_id"]
            if item_id not in items:
                items[item_id] = self.get_item(item_id)
            latest = items[item_id]["current_revision"]
            if latest["id"] != line["component_revision_id"]:
                updates[line["component_revision_id"]] = latest["label"]
            pending.extend(line.get("children", []))
        return updates

    def validate_references(self, references):
        from .workspace import bind_references

        return bind_references(self, references)

    def validate_native(self, path, references):
        from .fcstd import validate
        from .workspace import bind_references

        validate(path, bind_references(self, references), source_path=path)

    def upload_native(self, path, revision_id, item_id, references):
        from .workspace import upload

        return upload(self, path, revision_id, item_id, references)

    def retrieve_configuration(self, root, revision_id, dataset_id, file_id):
        from .workspace import retrieve

        return retrieve(self, root, revision_id, dataset_id, file_id)

    def finish_configuration(self, configuration):
        from .workspace import finish

        return finish(self, configuration)

    def _catalog_request(self, path):
        try:
            return self._json_request("GET", path)
        except ForgePDMError as error:
            if error.status == 404 and str(error) == "Not Found":
                raise ForgePDMError(
                    "This server does not support project/item browsing. Update or restart the ForgePDM backend.",
                    status=404,
                    code="unsupported_server",
                ) from error
            raise

    def standard_capabilities(self):
        return self._json_request("GET", "/api/v1/standard-parts/capabilities")

    def standard_matches(self, geometry):
        return self._json_request("POST", "/api/v1/standard-parts/matches", geometry)

    def create_item(
        self,
        kind,
        name,
        project_id=None,
        description="",
        number_series=None,
        standard_specification=None,
    ):
        payload = {"kind": kind, "name": name, "description": description}
        if number_series:
            payload["number_series"] = number_series
        if standard_specification is not None:
            payload["standard_specification"] = standard_specification
        if project_id:
            payload["project_id"] = project_id
        return self._json_request("POST", "/api/v1/items", payload)

    def get_item(self, item_id):
        return self._json_request("GET", "/api/v1/items/" + self._quote(item_id))

    def get_bom(self, revision_id, recursive=False):
        query = "?recursive=true" if recursive else ""
        return self._json_request(
            "GET", "/api/v1/revisions/" + self._quote(revision_id) + "/bom" + query
        )

    def get_checkout(self, revision_id):
        return self._json_request(
            "GET", "/api/v1/revisions/" + self._quote(revision_id) + "/checkout"
        )

    def bom_snapshot(self, revision_id):
        return self._json_request(
            "GET", "/api/v1/revisions/" + self._quote(revision_id) + "/bom/snapshot"
        )

    def synchronize_bom(self, revision_id, lines, snapshot):
        return self._json_request(
            "PUT",
            "/api/v1/revisions/" + self._quote(revision_id) + "/bom/synchronize",
            {
                "lines": lines,
                "expected_token": snapshot["token"],
                "expected_checkout_id": snapshot["checkout_id"],
            },
        )

    def prepare_cad_bom(self, path, revision_id, references):
        from .fcstd import validate
        from .workspace import WorkspaceError, bind_references, binding, digest

        value = binding(path, self.base_url)
        entry = value["entry"]
        current, _size = digest(path, self._checkpoint)
        if entry["revision_id"] != revision_id or current != entry["working_hash"]:
            raise WorkspaceError("Upload the saved assembly before synchronizing its BOM")
        manifest = self.get_manifest(entry["dataset_id"])
        if (
            manifest is None
            or manifest["source_file_id"] != entry["file_id"]
            or manifest["profile"] not in ("freecad-app-link-v1", "freecad-fasteners-v1")
        ):
            raise WorkspaceError("The assembly needs an uploaded pinned reference manifest")
        validate(path, manifest["references"])
        embedded = [r for r in references if r["property_name"] == "PDMStandardAssociation"]
        evidence = {r["object_name"]: r for r in manifest.get("standard_occurrences", [])}
        for captured in embedded:
            saved = evidence.get(captured["object_name"])
            if (
                not saved
                or saved["revision_id"] != captured["target_revision_id"]
                or saved["geometry"] != captured["geometry"]
                or saved["occurrence_id"] != captured["occurrence_id"]
            ):
                raise WorkspaceError(
                    "Fastener associations differ from the uploaded snapshot; upload again"
                )
        links = [r for r in references if r["property_name"] != "PDMStandardAssociation"]
        bound = bind_references(self, links)
        fields = ("target_revision_id", "target_dataset_id", "target_file_id", "target_object_name")
        pins = {tuple(ref[field] for field in fields) for ref in manifest["references"]}
        if any(tuple(ref[field] for field in fields) not in pins for ref in bound):
            raise WorkspaceError(
                "CAD occurrences differ from the uploaded assembly pins; upload again"
            )
        for ref, captured in zip(bound, links):
            ref["component_label"] = captured.get("component_label", ref["target_revision_id"])
        return {"references": bound + embedded, "source_hash": current}

    def synchronize_cad_bom(self, path, revision_id, references, source_hash, lines, snapshot):
        prepared = self.prepare_cad_bom(path, revision_id, references)
        if prepared["source_hash"] != source_hash:
            raise ForgePDMError("The assembly changed after review. Prepare a new BOM proposal.")
        return self.synchronize_bom(revision_id, lines, snapshot)

    def list_datasets(self, revision_id):
        return self._json_request(
            "GET", "/api/v1/revisions/" + self._quote(revision_id) + "/datasets"
        )

    def drawing_publication_status(self, revision_id, operation_id):
        try:
            return self._json_request(
                "GET",
                "/api/v1/revisions/{}/drawing-operations/{}".format(
                    self._quote(revision_id), self._quote(operation_id)
                ),
            )
        except ForgePDMError as error:
            if error.status == 404 and str(error) == "Not Found":
                raise ForgePDMError(
                    "Update/restart the backend to publish drawing PDFs", 404, "unsupported_server"
                ) from error
            if error.status == 404:
                return None
            raise

    def upload_drawing_publication(self, revision_id, bundle, intent):
        return self._multipart_file(
            "/api/v1/revisions/{}/drawings".format(self._quote(revision_id)),
            bundle,
            [("intent_json", json.dumps(intent, sort_keys=True))],
        )

    def prepare_drawings(self, path, revision_id, item_id, actor_id):
        from .drawing_publication import prepare

        return prepare(self, path, revision_id, item_id, actor_id)

    def freeze_drawings(self, plan, pages):
        from .drawing_publication import freeze

        return freeze(self, plan, pages)

    def resume_drawings(self, path, revision_id, item_id, actor_id):
        from .drawing_publication import resume

        return resume(self, path, revision_id, item_id, actor_id)

    def abandon_drawings(self, path, revision_id, item_id, actor_id):
        from .drawing_publication import abandon

        return abandon(self, path, revision_id, item_id, actor_id)

    def upload_file(self, revision_id, file_path, dataset_type="native_cad", name=None):
        if not self.token:
            raise ForgePDMError("Log in to ForgePDM before uploading")
        file_path = os.path.abspath(file_path)
        fields = [("dataset_type", dataset_type)]
        if name:
            fields.append(("name", name))
        endpoint = "/api/v1/revisions/{}/datasets".format(self._quote(revision_id))
        return self._multipart_file(endpoint, file_path, fields)

    def _multipart_file(self, endpoint, file_path, fields):
        if not self.token:
            raise ForgePDMError("Log in to ForgePDM before uploading")
        filename = os.path.basename(file_path)
        boundary = "----ForgePDM" + uuid.uuid4().hex
        file_header = (
            (
                '--{0}\r\nContent-Disposition: form-data; name="file"; filename="{1}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            )
            .format(boundary, self._safe_header_filename(filename))
            .encode("ascii")
        )
        field_parts = []
        for field_name, field_value in fields:
            field_parts.append(
                (
                    '--{0}\r\nContent-Disposition: form-data; name="{1}"\r\n\r\n{2}\r\n'.format(
                        boundary, field_name, field_value
                    )
                ).encode("utf-8")
            )
        closing = ("\r\n--{0}--\r\n".format(boundary)).encode("ascii")
        content_length = (
            sum(len(part) for part in field_parts)
            + len(file_header)
            + os.path.getsize(file_path)
            + len(closing)
        )

        connection = self._http_connection()
        try:
            self._checkpoint()
            target = self._target(endpoint)
            connection.putrequest("POST", target)
            connection.putheader("Authorization", "Bearer " + self.token)
            connection.putheader("Content-Type", "multipart/form-data; boundary=" + boundary)
            connection.putheader("Content-Length", str(content_length))
            connection.endheaders()
            for part in field_parts:
                connection.send(part)
            connection.send(file_header)
            with open(file_path, "rb") as source:
                completed = 0
                total = os.path.getsize(file_path)
                while True:
                    self._checkpoint(completed, total)
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    connection.send(chunk)
                    completed += len(chunk)
            connection.send(closing)
            response = connection.getresponse()
            return self._decode_response(response.status, response.read())
        except (OSError, http.client.HTTPException) as error:
            raise ForgePDMError(
                "File upload failed. Check your connection and the revision before retrying.",
                code="connection_failed",
            ) from error
        finally:
            connection.close()

    def part_checkin_status(self, revision_id, operation_id):
        try:
            return self._json_request(
                "GET",
                "/api/v1/revisions/{}/checkin-operations/{}".format(
                    self._quote(revision_id), self._quote(operation_id)
                ),
            )
        except ForgePDMError as error:
            if error.status == 404 and str(error) == "Not Found":
                raise ForgePDMError(
                    "Update/restart the backend: atomic part check-in is unavailable",
                    code="unsupported_server",
                ) from error
            if error.status == 404:
                return None
            raise

    def upload_part_checkin(self, snapshot_path, operation):
        fields = [
            (key, str(operation[key]))
            for key in (
                "operation_id",
                "expected_checkout_id",
                "expected_checkout_version",
                "content_hash",
                "byte_size",
            )
        ]
        if operation.get("references"):
            fields.append(("references_json", json.dumps(operation["references"], sort_keys=True)))
        suffix = (
            "checkin-native-with-references" if operation.get("references") else "checkin-native"
        )
        try:
            return self._multipart_file(
                "/api/v1/revisions/{}/{}".format(self._quote(operation["revision_id"]), suffix),
                snapshot_path,
                fields,
            )
        except ForgePDMError as error:
            if operation.get("references") and error.status == 404 and str(error) == "Not Found":
                raise ForgePDMError(
                    "Update/restart the backend: atomic CAD reference check-in is unavailable",
                    code="unsupported_server",
                ) from error
            raise

    def resume_part_checkin(self, path, revision_id, item_id, actor_id):
        from .part_checkin import resume

        return resume(self, path, revision_id, item_id, actor_id)

    def abandon_part_checkin(self, path, revision_id, item_id, actor_id):
        from .part_checkin import abandon

        return abandon(self, path, revision_id, item_id, actor_id)

    def checkin_part(self, path, revision_id, item_id, actor_id, references=()):
        from .part_checkin import checkin

        return checkin(self, path, revision_id, item_id, actor_id, references)

    def download_file(self, file_id, destination, expected_hash=None, expected_size=None):
        if not self.token:
            raise ForgePDMError("Log in to ForgePDM before downloading")
        url = self.base_url + "/api/v1/files/" + self._quote(file_id)
        request = urllib.request.Request(
            url,
            headers={"Authorization": "Bearer " + self.token},
            method="GET",
        )
        destination = os.path.abspath(destination)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".forgepdm-", suffix=".part", dir=os.path.dirname(destination)
        )
        os.close(descriptor)
        try:
            self._checkpoint()
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                completed = 0
                content_hash = hashlib.sha256()
                total = int(getattr(response, "headers", {}).get("Content-Length", 0))
                with open(temporary, "wb") as output:
                    while True:
                        self._checkpoint(completed, total)
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        content_hash.update(chunk)
                        completed += len(chunk)
            self._checkpoint(completed, total)
            if (expected_hash is not None and content_hash.hexdigest() != expected_hash) or (
                expected_size is not None and completed != expected_size
            ):
                raise ForgePDMError(
                    "Downloaded bytes failed SHA-256/size verification. No destination was published.",
                    code="integrity_failed",
                )
            # Same-directory staging permits atomic no-clobber publication.
            # Unlike an existence check followed by replace, link cannot
            # overwrite a file created by another process during the transfer.
            os.link(temporary, destination)
            return destination
        except FileExistsError as error:
            raise ForgePDMError(
                "The download destination already exists. Choose another filename."
            ) from error
        except urllib.error.HTTPError as error:
            self._raise_http_error(error)
        except (OSError, http.client.HTTPException) as error:
            raise ForgePDMError(
                "File download failed. Check your connection and try again.",
                code="connection_failed",
            ) from error
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    def checkin(self, revision_id, change_note=""):
        return self._json_request(
            "POST",
            "/api/v1/revisions/{}/checkin".format(self._quote(revision_id)),
            {"change_note": change_note},
        )

    def transition(self, revision_id, target):
        return self._json_request(
            "POST",
            "/api/v1/revisions/{}/lifecycle".format(self._quote(revision_id)),
            {"target": target},
        )

    def create_next_revision(self, item_id, change_note):
        return self._json_request(
            "POST",
            "/api/v1/items/{}/revisions".format(self._quote(item_id)),
            {"change_note": change_note},
        )

    def acquire_checkout(self, revision_id):
        return self._json_request(
            "POST", "/api/v1/revisions/{}/checkout".format(self._quote(revision_id))
        )

    def renew_checkout(self, revision_id):
        return self._json_request(
            "POST", "/api/v1/revisions/{}/checkout/renew".format(self._quote(revision_id))
        )

    def _json_request(self, method, path, payload=None, authenticated=True):
        self._checkpoint()
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            data = None
        if authenticated:
            if not self.token:
                raise ForgePDMError("Log in to ForgePDM first")
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = self._decode_response(response.status, response.read())
            return result
        except urllib.error.HTTPError as error:
            self._raise_http_error(error)
        except (OSError, http.client.HTTPException) as error:
            raise ForgePDMError(
                "Could not reach ForgePDM. Check the server URL and whether the server is running.",
                code="connection_failed",
            ) from error

    def _http_connection(self):
        host = self._parsed.hostname
        port = self._parsed.port
        if self._parsed.scheme == "https":
            return http.client.HTTPSConnection(
                host, port=port, timeout=self.timeout, context=ssl.create_default_context()
            )
        return http.client.HTTPConnection(host, port=port, timeout=self.timeout)

    def _target(self, endpoint):
        prefix = self._parsed.path.rstrip("/")
        return prefix + endpoint

    @staticmethod
    def _quote(value):
        return urllib.parse.quote(str(value), safe="")

    @staticmethod
    def _safe_header_filename(filename):
        filename = (
            filename.replace("\\", "_").replace('"', "_").replace("\r", "_").replace("\n", "_")
        )
        try:
            return filename.encode("ascii").decode("ascii")
        except UnicodeEncodeError:
            return re.sub(r"[^A-Za-z0-9._ -]", "_", filename)

    @staticmethod
    def _decode_response(status, body):
        if status >= 400:
            try:
                result = json.loads(body.decode("utf-8"))
                detail = result.get("detail", result) if isinstance(result, dict) else result
            except (ValueError, UnicodeError):
                detail = body.decode("utf-8", "replace")
            code = {
                401: "authentication_required",
                403: "permission_denied",
                409: "conflict",
                422: "validation_failed",
            }.get(status, "server_error" if status >= 500 else "request_failed")
            raise ForgePDMError(_error_message(detail, status), status, code)
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise ForgePDMError(
                "ForgePDM returned an invalid response. Check the server URL and server log.",
                code="invalid_response",
            )

    @staticmethod
    def _raise_http_error(error):
        body = error.read()
        ForgePDMClient._decode_response(error.code, body)
