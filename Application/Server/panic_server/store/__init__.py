"""The MongoDB repository layer (DATA_MODEL.md §1, §2).

``panic_server.store`` is the **only** package allowed to import ``pymongo`` / ``bson``
(AR-4.1, enforced by import-linter). Every public function returns ``panic_common.models``
or raises one of ``panic_server.store.errors`` — no pymongo/bson type ever leaks past this
package's boundary.
"""

from __future__ import annotations
