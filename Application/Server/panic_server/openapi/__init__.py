"""drf-spectacular schema-generation hooks (T-S6-06). ``hooks`` is imported for its side effect
(extension registration) by ``panic_server.api.urls``, which every management command that walks
the URLconf -- including ``manage.py spectacular`` -- always loads.
"""

from __future__ import annotations
