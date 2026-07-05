"""Telegram sendMessage + health alerts + digests (PLAN.md §Notifications).

Phase 3. Raw HTTPS POST to api.telegram.org/bot{TOKEN}/sendMessage (parse_mode=HTML,
disable_web_page_preview=true). Health alert if a run crashes or >20% of resolved
endpoints fail.
"""
from __future__ import annotations
