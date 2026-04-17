# hitl/__init__.py
# Human-In-The-Loop approval queue package.
#
# Phase 1: HitlManager (hitl/manager.py)
#   from hitl.manager import HitlManager
#   hm = HitlManager()
#   hm.get_pending(item_type="procurement")   → list[dict]
#   hm.approve(item_id, comment, approved_by) → bool
#   hm.reject(item_id, comment, rejected_by)  → bool
#   hm.get_counts()                           → dict {type: count, total: N}

