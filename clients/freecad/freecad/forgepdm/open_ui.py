"""One asynchronous search, revision and snapshot window for opening CAD."""

from concurrent.futures import ThreadPoolExecutor
from html import escape

from .jobs import OperationCancelled, Request, WorkflowJob
from .open_model import snapshot_label, snapshots, validate_workspace
from .ui import QtCore, QtWidgets


class SourceTabs(QtWidgets.QTabBar):
    def currentData(self):
        return self.tabData(self.currentIndex())


class OpenDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent,
        client,
        root,
        choose_workspace,
        *,
        actor_id=None,
        library=None,
        on_open=None,
        session_valid=None,
    ):
        super().__init__(parent)
        self.client, self.choose_workspace = client, choose_workspace
        self.actor_id, self.on_open = actor_id, on_open
        self.session_valid = session_valid or (lambda: True)
        self.library = library
        if self.library is None and actor_id:
            from .browser_library import BrowserLibrary

            self.library = BrowserLibrary(client.base_url, actor_id)
        self.open_job = None
        if on_open is not None:
            self.setWindowFlags(QtCore.Qt.Widget)
        self.root, self.selection = root, None
        self.jobs = []
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="ForgePDM-Search")
        self.search_epoch = self.detail_epoch = self.snapshot_epoch = 0
        self.offset = self.revision_offset = 0
        self.item = None
        self.open_when_ready = False
        self.finishing = False
        self.outcome = 0
        self.setWindowTitle("Open from ForgePDM")
        self.resize(940, 620)
        layout = QtWidgets.QVBoxLayout(self)
        sources = QtWidgets.QHBoxLayout()
        self.source = SourceTabs()
        self.source.setExpanding(False)
        self.source.setObjectName("forgepdm_browser_source")
        for label, value in [
            ("All Items", "catalog"),
            ("Recent", "recent"),
            ("Favorites", "favorites"),
            ("My Checkouts", "checkouts"),
        ]:
            self.source.setTabData(self.source.addTab(label), value)
        layout.addWidget(self.source)
        sources.addStretch()
        self.refresh = QtWidgets.QPushButton("Refresh")
        self.favorite = QtWidgets.QPushButton("☆ Favorite")
        self.favorite.setEnabled(False)
        self.clear_recent = QtWidgets.QPushButton("Clear Recent")
        self.clear_recent.hide()
        sources.addWidget(self.favorite)
        sources.addWidget(self.clear_recent)
        sources.addWidget(self.refresh)
        layout.addLayout(sources)
        search_row = QtWidgets.QHBoxLayout()
        self.query = QtWidgets.QLineEdit()
        self.query.setObjectName("forgepdm_open_search")
        self.query.setPlaceholderText("Search item number, name or description…")
        self.query.setMaxLength(200)
        self.query.setClearButtonEnabled(True)
        search_row.addWidget(self.query, 1)
        self.series = QtWidgets.QComboBox()
        for label, value in [
            ("All items", None),
            ("Parts", "P"),
            ("Assemblies", "A"),
            ("Standard / purchased", "S"),
        ]:
            self.series.addItem(label, value)
        search_row.addWidget(self.series)
        layout.addLayout(search_row)
        self.results = QtWidgets.QTreeWidget()
        self.results.setObjectName("forgepdm_open_results")
        self.results.setHeaderLabels(["Item", "Description", "Revision", "Lifecycle"])
        self.results.setRootIsDecorated(False)
        self.results.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        header = self.results.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(60)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        for column in (0, 2, 3):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        layout.addWidget(self.results, 1)
        paging = QtWidgets.QHBoxLayout()
        self.previous = QtWidgets.QPushButton("← Previous")
        self.next = QtWidgets.QPushButton("Next →")
        self.page_label = QtWidgets.QLabel()
        paging.addWidget(self.previous)
        paging.addWidget(self.page_label, 1)
        paging.addWidget(self.next)
        layout.addLayout(paging)
        form = QtWidgets.QFormLayout()
        self.revision = QtWidgets.QComboBox()
        self.revision.setObjectName("forgepdm_open_revision")
        revision_row = QtWidgets.QHBoxLayout()
        revision_row.addWidget(self.revision, 1)
        self.older = QtWidgets.QPushButton("Load older revisions")
        revision_row.addWidget(self.older)
        form.addRow("Revision", revision_row)
        self.snapshot = QtWidgets.QComboBox()
        self.snapshot.setObjectName("forgepdm_open_snapshot")
        form.addRow("Uploaded CAD", self.snapshot)
        self.workspace = QtWidgets.QLabel(root or "Choose a workspace once")
        self.workspace.setTextFormat(QtCore.Qt.PlainText)
        self.workspace.setWordWrap(True)
        workspace_row = QtWidgets.QHBoxLayout()
        workspace_row.addWidget(self.workspace, 1)
        self.change_workspace = QtWidgets.QPushButton("Change…")
        workspace_row.addWidget(self.change_workspace)
        form.addRow("Workspace", workspace_row)
        layout.addLayout(form)
        defaults = QtWidgets.QLabel(
            "Default: current revision and newest uploaded CAD. Components keep their recorded revisions. Opening does not check out."
        )
        defaults.setWordWrap(True)
        layout.addWidget(defaults)
        self.defaults = defaults
        self.status = QtWidgets.QLabel("Loading items…")
        self.status.setTextFormat(QtCore.Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        self.open_button = QtWidgets.QPushButton("Open")
        self.open_button.setObjectName("forgepdm_open_button")
        self.open_button.setEnabled(False)
        close = QtWidgets.QPushButton("Hide" if on_open else "Cancel")
        buttons.addWidget(self.open_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        for button in self.findChildren(QtWidgets.QPushButton):
            button.setAutoDefault(False)
        self.debounce = QtCore.QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(250)
        self.debounce.timeout.connect(self.search)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(30)
        self.query.textChanged.connect(self.changed)
        self.series.currentIndexChanged.connect(self.changed)
        self.query.returnPressed.connect(self.enter_search)
        self.results.itemSelectionChanged.connect(self.select_item)
        self.results.itemActivated.connect(lambda *_: self.request_open())
        self.revision.currentIndexChanged.connect(self.select_revision)
        self.snapshot.currentIndexChanged.connect(self.ready)
        self.previous.clicked.connect(lambda: self.page(-50))
        self.next.clicked.connect(lambda: self.page(50))
        self.older.clicked.connect(self.load_older)
        self.change_workspace.clicked.connect(self.change_root)
        self.open_button.clicked.connect(self.request_open)
        close.clicked.connect(self.reject)
        self.source.currentChanged.connect(self.changed)
        self.refresh.clicked.connect(self.search)
        self.favorite.clicked.connect(self.toggle_favorite)
        self.clear_recent.clicked.connect(self.forget_recent)
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.older.hide()
        self.query.installEventFilter(self)
        self.query.setFocus()
        if on_open is None:
            QtCore.QTimer.singleShot(0, self.search)

    def eventFilter(self, watched, event):
        if (
            watched is self.query
            and event.type() == QtCore.QEvent.KeyPress
            and event.key() == QtCore.Qt.Key_Down
            and self.results.topLevelItemCount()
        ):
            self.results.setFocus()
            if self.results.currentItem() is None:
                self.results.setCurrentItem(self.results.topLevelItem(0))
            return True
        return super().eventFilter(watched, event)

    def start(self, label, function, args, kwargs, valid, loaded):
        local_valid = valid

        def valid():
            return local_valid() and self.session_valid()

        def run():
            result = yield Request(label, function, args, kwargs)
            if valid() and not self.finishing:
                loaded(result)

        job = WorkflowJob(run(), executor=self.executor)
        self.jobs.append((job, valid))
        job.start()

    def poll(self):
        for job, valid in self.jobs[:]:
            if not valid():
                job.cancel()
            job.poll()
            if job.done:
                self.jobs.remove((job, valid))
                if (
                    job.error
                    and not isinstance(job.error, OperationCancelled)
                    and valid()
                    and not self.finishing
                ):
                    self.open_when_ready = False
                    self.open_button.setEnabled(False)
                    self.status.setText(str(job.error))
                    if getattr(job.error, "status", None) == 401:
                        from .session import Session

                        if Session.client is self.client:
                            Session.invalidate()
        if self.open_job is not None and self.open_job.done:
            error = self.open_job.error
            self.open_job = None
            if not self.finishing and self.session_valid():
                self.setEnabled(True)
                self.ready()
                if error:
                    self.status.setText(str(error))
                elif self.source.currentData() == "recent":
                    self.search()
        if self.finishing and not self.jobs and self.open_job is None:
            self.timer.stop()
            self.executor.shutdown(wait=False, cancel_futures=True)
            super().done(self.outcome)

    def clear_details(self):
        self.detail_epoch += 1
        self.snapshot_epoch += 1
        self.item = None
        self.favorite.setEnabled(False)
        self.open_button.setEnabled(False)
        self.revision.blockSignals(True)
        self.revision.clear()
        self.revision.blockSignals(False)
        self.snapshot.clear()
        self.older.hide()

    def changed(self, *_):
        self.search_epoch += 1
        self.offset = 0
        self.open_when_ready = False
        self.clear_details()
        self.results.clear()
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.status.setText("Searching…")
        self.debounce.start()

    def search(self):
        if self.finishing:
            return
        self.search_epoch += 1
        epoch = self.search_epoch
        self.results.blockSignals(True)
        self.results.clear()
        self.results.blockSignals(False)
        self.clear_details()
        self.status.setText("Searching…")
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        source = self.source.currentData()
        self.clear_recent.setVisible(source == "recent")
        self.defaults.setText(
            "Recent Items keeps the exact revision and uploaded snapshot previously opened."
            if source == "recent"
            else "My Checkouts shows your active and expired leases. Opening does not renew or acquire checkout."
            if source == "checkouts"
            else "Default: current revision and newest uploaded CAD. Components keep their recorded revisions. Opening does not check out."
        )
        options = {"number_series": self.series.currentData(), "limit": 50, "offset": self.offset}
        if source == "catalog":
            function, args = self.client.search_items, (self.query.text().strip(),)
        else:
            try:
                library = (
                    self.library.load()
                    if self.library and source in ("recent", "favorites")
                    else {"recent": [], "favorites": []}
                )
            except (ValueError, RuntimeError) as error:
                self.status.setText(str(error))
                return
            entries = library.get(source, [])
            function, args = self.client.browser_items, (source, entries, self.query.text().strip())
        self.start(
            "Loading items…",
            function,
            args,
            options,
            lambda: epoch == self.search_epoch,
            self.items_loaded,
        )

    def items_loaded(self, page):
        self.results.blockSignals(True)
        self.results.clear()
        for record in page["items"]:
            row = QtWidgets.QTreeWidgetItem(
                self.results,
                [
                    record["number"],
                    record.get("revision_description") or record.get("description", ""),
                    record["revision_label"],
                    record["lifecycle_state"]
                    + (" · expired checkout" if record.get("checkout_status") == "expired" else ""),
                ],
            )
            row.setData(0, QtCore.Qt.UserRole, record)
            row.setToolTip(1, "<qt>" + escape(row.text(1)).replace("\n", "<br/>") + "</qt>")
        self.results.blockSignals(False)
        self.previous.setEnabled(page["offset"] > 0)
        self.next.setEnabled(page["has_more"])
        self.page_label.setText(
            "{}–{}".format(page["offset"] + 1, page["offset"] + len(page["items"]))
            if page["items"]
            else "No results"
        )
        self.results.setToolTip(
            "Some shortcuts are unavailable with your current access."
            if page.get("unavailable")
            else ""
        )
        if page.get("truncated"):
            self.page_label.setText(self.page_label.text() + " · first 1000 checkouts")
        if page["items"]:
            self.results.setCurrentItem(self.results.topLevelItem(0))
        else:
            self.open_when_ready = False
            self.status.setText("No matching items. Try another number, description or filter.")

    def page(self, step):
        self.open_when_ready = False
        self.offset = max(0, self.offset + step)
        self.search()

    def enter_search(self):
        self.open_when_ready = True
        if self.debounce.isActive():
            self.debounce.stop()
            self.search()
        else:
            self.request_open()

    def select_item(self):
        self.clear_details()
        rows = self.results.selectedItems()
        if not rows:
            return
        self.item = rows[0].data(0, QtCore.Qt.UserRole)
        self.update_favorite()
        epoch = self.detail_epoch
        self.revision_offset = 0
        self.status.setText("Loading revisions…")
        self.start(
            "Loading revisions…",
            self.client.list_revisions,
            (self.item["id"],),
            {"limit": 100, "offset": 0},
            lambda: epoch == self.detail_epoch,
            lambda page: self.revisions_loaded(page, False),
        )

    def revisions_loaded(self, page, append):
        self.revision.blockSignals(True)
        records = list(page["items"])
        preferred = self.item.get("preferred_revision")
        if (
            not append
            and preferred
            and not any(record["id"] == preferred["id"] for record in records)
        ):
            records.insert(0, preferred)
        for record in records:
            if any(
                self.revision.itemData(i)["id"] == record["id"]
                for i in range(self.revision.count())
            ):
                continue
            label = "{} — {}".format(record["label"], record["lifecycle_state"])
            if record["id"] == self.item["current_revision_id"]:
                label += " (current)"
            self.revision.addItem(label, record)
        self.revision_offset = page["offset"] + len(page["items"])
        self.older.setVisible(page["has_more"])
        self.older.setEnabled(True)
        if not append:
            index = next(
                (
                    i
                    for i in range(self.revision.count())
                    if self.revision.itemData(i)["id"]
                    == (preferred["id"] if preferred else self.item["current_revision_id"])
                ),
                0,
            )
            self.revision.setCurrentIndex(index)
        self.revision.blockSignals(False)
        if not append:
            self.select_revision()

    def load_older(self):
        epoch = self.detail_epoch
        self.older.setEnabled(False)
        self.start(
            "Loading older revisions…",
            self.client.list_revisions,
            (self.item["id"],),
            {"limit": 100, "offset": self.revision_offset},
            lambda: epoch == self.detail_epoch,
            lambda page: self.revisions_loaded(page, True),
        )

    def select_revision(self, *_):
        self.snapshot_epoch += 1
        epoch = self.snapshot_epoch
        self.open_button.setEnabled(False)
        self.snapshot.clear()
        revision = self.revision.currentData()
        if not revision:
            self.open_when_ready = False
            self.status.setText("No revision is available.")
            return
        self.status.setText("Loading uploaded CAD…")
        self.start(
            "Loading uploaded CAD…",
            self.client.list_datasets,
            (revision["id"],),
            {},
            lambda: epoch == self.snapshot_epoch,
            self.snapshots_loaded,
        )

    def snapshots_loaded(self, datasets):
        self.snapshot.blockSignals(True)
        for index, (dataset, record) in enumerate(snapshots(datasets)):
            self.snapshot.addItem(
                snapshot_label(dataset, record, newest=index == 0), (dataset, record)
            )
            self.snapshot.setItemData(index, record.get("content_hash", ""), QtCore.Qt.ToolTipRole)
        pinned = (
            self.item
            and self.item.get("preferred_dataset_id")
            and self.revision.currentData()["id"] == self.item["preferred_revision"]["id"]
        )
        if pinned:
            index = next(
                (
                    i
                    for i in range(self.snapshot.count())
                    if self.snapshot.itemData(i)[0]["id"] == self.item["preferred_dataset_id"]
                    and self.snapshot.itemData(i)[1]["id"] == self.item["preferred_file_id"]
                ),
                -1,
            )
            self.snapshot.setCurrentIndex(index)
        self.snapshot.blockSignals(False)
        self.ready()
        if pinned and self.snapshot.currentIndex() < 0:
            self.status.setText(
                "The recorded upload is unavailable. Choose another snapshot explicitly."
            )
        if self.open_when_ready:
            self.request_open()

    def ready(self, *_):
        available = bool(self.snapshot.currentData()) and self.item is not None
        self.open_button.setEnabled(available)
        self.status.setText(
            "Press Enter or double-click an item to open."
            if available
            else "This revision has no uploaded native CAD. Choose another revision or item."
        )
        if not available:
            self.open_when_ready = False

    def change_root(self):
        try:
            root = self.choose_workspace()
            if root:
                self.root = root
                self.workspace.setText(root)
        except Exception as error:
            self.status.setText(str(error))

    def request_open(self):
        if self.finishing:
            return
        if not self.open_button.isEnabled():
            self.open_when_ready = True
            return
        self.open_when_ready = False
        try:
            validate_workspace(self.root, self.client.base_url)
        except Exception:
            self.change_root()
        try:
            root = validate_workspace(self.root, self.client.base_url)
        except Exception as error:
            self.status.setText(str(error))
            return
        dataset, record = self.snapshot.currentData()
        self.selection = {
            "item": self.item,
            "revision": self.revision.currentData(),
            "dataset": dataset,
            "file": record,
            "workspace": root,
        }
        if self.actor_id:
            self.selection["actor_id"] = self.actor_id
        if self.on_open is not None:
            try:
                if not self.session_valid():
                    raise RuntimeError("The session changed; reopen the ForgePDM browser.")
                job = self.on_open(self.selection)
                if job is not None:
                    self.open_job = job
                    self.setEnabled(False)
                    self.status.setText("Opening the selected configuration…")
            except Exception as error:
                self.status.setText(str(error))
            return
        self.finish(1)

    def finish(self, outcome):
        self.finishing, self.outcome = True, outcome
        self.debounce.stop()
        self.setEnabled(False)
        self.status.setText("Waiting for pending requests to stop…")
        for job, _ in self.jobs:
            job.cancel()
        if not self.jobs and self.open_job is None:
            self.timer.stop()
            self.executor.shutdown(wait=False, cancel_futures=True)
            super().done(outcome)

    def update_favorite(self):
        self.favorite.setEnabled(bool(self.library and self.item))
        if not self.library or not self.item:
            return
        try:
            favorite = self.item["id"] in self.library.load()["favorites"]
            self.favorite.setText("★ Favorited" if favorite else "☆ Favorite")
        except (ValueError, RuntimeError) as error:
            self.favorite.setEnabled(False)
            self.status.setText(str(error))

    def toggle_favorite(self):
        if not self.library or not self.item:
            return
        try:
            self.library.toggle_favorite(self.item["id"])
            self.update_favorite()
            if self.source.currentData() == "favorites":
                self.search()
        except (ValueError, RuntimeError) as error:
            self.status.setText(str(error))

    def forget_recent(self):
        if self.library:
            try:
                self.library.clear_recent()
                self.search()
            except (ValueError, RuntimeError) as error:
                self.status.setText(str(error))

    def pause(self, clear=False):
        self.search_epoch += 1
        self.detail_epoch += 1
        self.snapshot_epoch += 1
        self.debounce.stop()
        self.open_when_ready = False
        for job, _ in self.jobs:
            job.cancel()
        if clear:
            self.clear_details()
            self.results.clear()
            self.workspace.clear()
            self.query.clear()
            self.debounce.stop()

    def reject(self):
        if self.on_open is not None and not self.finishing:
            self.pause()
            self.parentWidget().hide()
            return
        self.selection = None
        self.finish(0)

    def closeEvent(self, event):
        event.ignore()
        self.reject()
