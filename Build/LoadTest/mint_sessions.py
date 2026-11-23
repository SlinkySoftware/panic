"""Piped into ``python -m django shell`` inside a panic-server container: create one real
server-side session per seeded load user and print ``{username: session_key}`` as JSON on the last line."""

import json

from panic_server.context import SESSION_USER_KEY
from panic_server.store.client import get_db
from panic_server.store.repos import users as users_repo
from panic_server.store.sessions import SessionStore

out = {}
for user in users_repo.list_users(get_db(), disabled=False):
    if not user.username.startswith("loaduser"):
        continue
    s = SessionStore()
    s[SESSION_USER_KEY] = user.id
    s.set_expiry(6 * 3600)
    s.create()
    out[user.username] = s.session_key
print(json.dumps(out))
