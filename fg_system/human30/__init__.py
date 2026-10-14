# fg_system/human30/__init__.py
# -*- coding: utf-8 -*-
"""Human 3.0 v2（忠实版）。见 docs/human30-v2-design.md。

对外 API = re-export model / store / metrics 的全部名字，
保证 `from fg_system import human30` 与 v1 完全兼容（守卫见 tests/human30/test_compat_surface.py）。
"""
from . import model, store, metrics                      # noqa: F401
from .model import (                                     # noqa: F401
    QUADRANTS, LABELS, LEVELS, PHASES, PHASE_LABELS, TRAITS,
    AQAL_POSITIONS, ARCHETYPES, LIFESTYLE_ARCHETYPES,
    FALSE_TRANSFORMATION, UNLOCK_SEQUENCES, BLOCK_PATTERNS,
    KEY_PRINCIPLES, TOTAL_SLICES, QUESTIONS, LIKERT_SCORES,
)
from .store import (                                     # noqa: F401
    DATA_PATH, _load, _save, record, latest, history,
    bucket_level, migrate_record,
)
from .metrics import (                                   # noqa: F401
    aggregate, advice, brief_line, days_since_last, window_stats,
    to_csv, insight_summary, answers_to_scores, record_from_answers,
)
