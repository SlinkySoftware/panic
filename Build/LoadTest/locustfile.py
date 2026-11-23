"""Load scenario: 50 signed-in users through panic-web, spread over 4 zones via XFF.

Request mix: 35% dashboard view (60% of those revalidate with If-None-Match),
15% bootstrap, 15% palette search (3 keystroke queries), 15% catalog page/filter, 5% list detail,
5% .rdp launch, 10% mutations (layout save on the user's own dashboard, profile save).
Env: PANIC_LT_SESSIONS (JSON file from mint_sessions.py), PANIC_LT_NO_THINK=1 for the stress run.
"""

from __future__ import annotations

import itertools
import json
import os
import random
import threading

from locust import HttpUser, between, constant, task

SESSIONS: dict[str, str] = json.load(open(os.environ["PANIC_LT_SESSIONS"]))
_NAMES = sorted(SESSIONS)
_next = itertools.count()
_lock = threading.Lock()
# Loadtest zones are 2001:db8:<i>::/48 (fixtures/loadtest.py); use four of them.
ZONE_IPS = [f"2001:db8:{i:04x}::10" for i in (1, 2, 3, 4)]
# Seeded titles are "Load Item 00042", "Load List 001", "Load Dashboard 000": every word below matches.
WORDS = ["load", "item", "list", "dash", "00042", "0123", "item 01", "load item 3"]


class PanicUser(HttpUser):
    wait_time = constant(0) if os.environ.get("PANIC_LT_NO_THINK") else between(2, 5)

    def on_start(self) -> None:
        with _lock:
            n = next(_next)
        self.username = _NAMES[n % len(_NAMES)]
        self.client.cookies.set("panic_sessionid", SESSIONS[self.username])
        self.client.headers["X-Forwarded-For"] = ZONE_IPS[n % len(ZONE_IPS)]
        self.etags: dict[str, str] = {}
        self.client.get("/api/v1/auth/csrf", name="csrf")
        self.client.headers["X-CSRFToken"] = self.client.cookies.get("panic_csrftoken", "")
        boot = self.client.get("/api/v1/ui/bootstrap", name="bootstrap").json()
        self.dashboards = [d["id"] for d in boot["nav"]["dashboards"]] or [boot["default_dashboard"]["id"]]
        page = self.client.get("/api/v1/catalog?group=shared&page=1&page_size=100", name="catalog page").json()
        self.rdp_ids = [i["id"] for i in page["results"] if i["protocol"] == "RDP"]
        lists = self.client.get("/api/v1/lists?group=shared&page=1&page_size=50", name="lists page").json()
        self.list_ids = [x["id"] for x in lists["results"]]
        mine = self.client.post(
            "/api/v1/dashboards", json={"title": f"lt {self.username}", "scope": "PERSONAL"}, name="setup dashboard"
        ).json()
        self.my_dashboard = mine["id"]

    @task(35)
    def dashboard(self) -> None:
        d = random.choice(self.dashboards)
        etag = self.etags.get(d)
        if etag and random.random() < 0.6:
            with self.client.get(
                f"/api/v1/ui/dashboards/{d}", headers={"If-None-Match": etag}, name="dashboard 304", catch_response=True
            ) as r:
                if r.status_code in (200, 304):
                    r.success()
            return
        r = self.client.get(f"/api/v1/ui/dashboards/{d}", name="dashboard 200")
        if r.ok:
            self.etags[d] = r.headers.get("ETag", "")
            items = len(r.json()["items"])
            bucket = "200+" if items >= 200 else "100-199" if items >= 100 else "<100"
            # extra sample bucketed by resolved items (all seeded dashboards have 3 widgets; payload
            # size depends on the lists), so typical vs largest can be read off the stats
            self.environment.events.request.fire(
                request_type="GET", name=f"dashboard 200 items {bucket}",
                response_time=r.elapsed.total_seconds() * 1000, response_length=len(r.content),
                exception=None, context={},
            )

    @task(15)
    def bootstrap(self) -> None:
        self.client.get("/api/v1/ui/bootstrap", name="bootstrap")

    @task(15)
    def search(self) -> None:
        word = random.choice(WORDS)
        for n in (len(word) - 2, len(word) - 1, len(word)):  # three keystroke queries ending in the full word
            self.client.get(f"/api/v1/ui/search?q={word[:n]}&limit=20", name="search")

    @task(15)
    def catalog(self) -> None:
        group = random.choice(["shared", "personal"])
        q = random.choice(["", "load", "host", "web"])
        proto = random.choice(["", "", "SSH", "RDP", "WEB"])
        # Deeper pages only where they exist: unfiltered shared (3,000+ items); ~10 personal per user.
        page = random.randint(1, 5) if group == "shared" and not q and not proto else 1
        self.client.get(
            f"/api/v1/catalog?group={group}&q={q}&protocol={proto}&page={page}&page_size=50", name="catalog page"
        )

    @task(5)
    def list_detail(self) -> None:
        if self.list_ids:
            self.client.get(f"/api/v1/lists/{random.choice(self.list_ids)}", name="list detail")

    @task(5)
    def launch(self) -> None:
        if self.rdp_ids:
            self.client.get(f"/api/v1/launch/rdp/{random.choice(self.rdp_ids)}.rdp", name="rdp launch")

    @task(10)
    def mutate(self) -> None:
        if random.random() < 0.5:
            d = self.client.get(f"/api/v1/dashboards/{self.my_dashboard}", name="mutation read").json()
            with self.client.put(
                f"/api/v1/dashboards/{self.my_dashboard}/layout",
                json={"widgets": d["widgets"]},
                headers={"If-Match": f'"{d["version"]}"'},
                name="mutation layout save",
                catch_response=True,
            ) as r:
                if r.status_code in (200, 409):  # 409 = intended conflict, not an error
                    r.success()
        else:
            me = self.client.get("/api/v1/me", name="mutation read").json()
            with self.client.patch(
                "/api/v1/me",
                json={"display_name": me["display_name"]},
                headers={"If-Match": f'"{me["version"]}"'},
                name="mutation profile save",
                catch_response=True,
            ) as r:
                if r.status_code in (200, 409):
                    r.success()
