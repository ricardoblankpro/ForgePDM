"""Small standard-library HTTP client for the ForgePDM API."""

import http.client
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid


class ForgePDMError(Exception):
    def __init__(self, message, status=None):
        Exception.__init__(self, message)
        self.status = status


class ForgePDMClient:
    """API client with a memory-only bearer token and streamed file transfer."""

    def __init__(self, base_url, timeout=60):
        self.base_url = base_url.strip().rstrip("/")
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("Server URL must start with http:// or https://")
        self._parsed = parsed
        self.timeout = timeout
        self.token = None

    def login(self, username, password):
        result = self._json_request(
            "POST",
            "/api/v1/auth/login",
            {"username": username, "password": password},
            authenticated=False,
        )
        self.token = result["access_token"]
        return result["user"]

    def logout(self):
        if self.token:
            try:
                self._json_request("POST", "/api/v1/auth/logout", None)
            finally:
                self.token = None

    def create_item(self, kind, name, project_id=None, description=""):
        payload = {"kind": kind, "name": name, "description": description}
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

    def list_datasets(self, revision_id):
        return self._json_request(
            "GET", "/api/v1/revisions/" + self._quote(revision_id) + "/datasets"
        )

    def upload_file(self, revision_id, file_path, dataset_type="native_cad", name=None):
        if not self.token:
            raise ForgePDMError("Log in to ForgePDM before uploading")
        file_path = os.path.abspath(file_path)
        filename = os.path.basename(file_path)
        fields = [("dataset_type", dataset_type)]
        if name:
            fields.append(("name", name))
        boundary = "----ForgePDM" + uuid.uuid4().hex
        endpoint = "/api/v1/revisions/{}/datasets".format(self._quote(revision_id))
        file_header = (
            "--{0}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{1}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n"
        ).format(boundary, self._safe_header_filename(filename)).encode("ascii")
        field_parts = []
        for field_name, field_value in fields:
            field_parts.append(
                ("--{0}\r\nContent-Disposition: form-data; name=\"{1}\"\r\n\r\n{2}\r\n".format(
                    boundary, field_name, field_value
                )).encode("utf-8")
            )
        closing = ("\r\n--{0}--\r\n".format(boundary)).encode("ascii")
        content_length = sum(len(part) for part in field_parts) + len(file_header) + os.path.getsize(file_path) + len(closing)

        connection = self._http_connection()
        try:
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
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    connection.send(chunk)
            connection.send(closing)
            response = connection.getresponse()
            return self._decode_response(response.status, response.read())
        except (OSError, http.client.HTTPException) as error:
            raise ForgePDMError("File upload failed: {}".format(error))
        finally:
            connection.close()

    def download_file(self, file_id, destination):
        if not self.token:
            raise ForgePDMError("Log in to ForgePDM before downloading")
        url = self.base_url + "/api/v1/files/" + self._quote(file_id)
        request = urllib.request.Request(
            url,
            headers={"Authorization": "Bearer " + self.token},
            method="GET",
        )
        destination = os.path.abspath(destination)
        temporary = destination + ".part"
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                with open(temporary, "wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
            os.replace(temporary, destination)
            return destination
        except urllib.error.HTTPError as error:
            self._raise_http_error(error)
        except (OSError, urllib.error.URLError) as error:
            raise ForgePDMError("File download failed: {}".format(error))
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    def checkin(self, revision_id, change_note):
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
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return self._decode_response(response.status, response.read())
        except urllib.error.HTTPError as error:
            self._raise_http_error(error)
        except urllib.error.URLError as error:
            raise ForgePDMError("Could not reach ForgePDM: {}".format(error.reason))

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
        filename = filename.replace("\\", "_").replace('"', "_").replace("\r", "_").replace("\n", "_")
        try:
            return filename.encode("ascii").decode("ascii")
        except UnicodeEncodeError:
            return re.sub(r"[^A-Za-z0-9._ -]", "_", filename)

    @staticmethod
    def _decode_response(status, body):
        if status >= 400:
            try:
                result = json.loads(body.decode("utf-8"))
                detail = result.get("detail", result)
            except (ValueError, UnicodeError):
                detail = body.decode("utf-8", "replace")
            raise ForgePDMError(str(detail), status)
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeError):
            return body

    @staticmethod
    def _raise_http_error(error):
        body = error.read()
        ForgePDMClient._decode_response(error.code, body)
