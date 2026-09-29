"""One resumable local subscription per project, independent of browser tabs."""
from __future__ import annotations

import fcntl
import threading
from datetime import datetime, timezone

import httpx

from orchestrator.blackmagician.client import IntegrationError
from orchestrator.blackmagician.review import read_object
from orchestrator.blackmagician.service import private_json


class LiveSessions:
    def __init__(self, service):
        self.service = service
        self.stopped = threading.Event()
        self.workers = {}
        self.lock = threading.Lock()

    def resume(self):
        for project in self.service.registry.load()['projects']:
            if not project.get('removed_at'):
                self.ensure(project['id'])

    def ensure(self, project_id):
        if self.stopped.is_set():
            return
        with self.lock:
            old = self.workers.get(project_id)
            if old and old.is_alive():
                return
            state = read_object(self.service.folder(project_id) / 'state.json')
            if not state.get('connection') or not state.get('live', {}).get('enabled'):
                return
            worker = threading.Thread(target=self.run, args=(project_id,), daemon=True,
                                      name='blackmagician-live-' + project_id)
            self.workers[project_id] = worker
            worker.start()

    def close(self):
        self.stopped.set()
        # Network reads have a bounded timeout; workers also check the stop flag
        # before committing, so shutdown cannot publish late observations.

    def commit(self, project_id, generation, snapshot=None, *, error=None, heartbeat=False):
        if self.stopped.is_set():
            return False
        with self.service.locked(project_id) as folder:
            state = read_object(folder / 'state.json')
            connection, live = state.get('connection') or {}, state.get('live') or {}
            if connection.get('generation') != generation or not live.get('enabled'):
                return False
            if snapshot is not None:
                self.service.apply_snapshot(state, snapshot)
            elif error:
                terminal = getattr(error, 'status', None) in {401, 403, 404, 410}
                message = str(error) if isinstance(error, IntegrationError) else '촬영 연결이 끊겼습니다. 자동으로 다시 연결합니다.'
                live.update(status='reauth_required' if terminal else 'reconnecting', last_error=message)
                connection.update(status='reauth_required' if terminal else 'stale', last_error=message)
            elif heartbeat:
                live['last_received_at'] = datetime.now(timezone.utc).isoformat()
            private_json(folder / 'state.json', state)
            return True

    def run(self, project_id):
        try:
            self._run(project_id)
        except (OSError, IntegrationError):
            # Removed projects and an app shutting down do not restart workers.
            return

    def _run(self, project_id):
        folder = self.service.folder(project_id)
        with (folder / '.live.lock').open('a') as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            retry = 1
            while not self.stopped.is_set():
                self.service.folder(project_id)  # Stop when the local project is removed.
                state = read_object(folder / 'state.json')
                connection, live = state.get('connection'), state.get('live') or {}
                if not connection or not live.get('enabled'):
                    return
                if connection.get('environment', 'production') != self.service.environment():
                    return
                if live.get('status') == 'reauth_required':
                    if self.stopped.wait(1):
                        return
                    continue
                generation = connection.get('generation')
                client = self.service.client_factory()
                try:
                    ended = (state.get('snapshot') or {}).get('camera', {}) or {}
                    if connection['mode'] == 'invite' and not ended.get('isSessionEnded'):
                        for snapshot in client.watch(connection, self.stopped):
                            if not self.commit(project_id, generation, snapshot, heartbeat=snapshot is None):
                                break
                            retry = 1
                            if snapshot and (snapshot.get('camera') or {}).get('isSessionEnded'):
                                break
                    else:
                        self.commit(project_id, generation, client.snapshot(connection))
                        retry = 1
                        # Ended sessions remain reconcilable for late script edits.
                        self.stopped.wait(15 if ended.get('isSessionEnded') else 3)
                except (httpx.HTTPError, IntegrationError, ValueError, KeyError, TypeError) as exc:
                    self.commit(project_id, generation, error=exc)
                    self.stopped.wait(retry)
                    retry = min(retry * 2, 30)
                finally:
                    client.close()
