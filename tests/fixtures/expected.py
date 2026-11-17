"""脏样例的期望值：改动规则或样例时必须同步这里。

所有数字都来自 sample_data/tickets_dirty.csv 的一次真实运行。
"""

DIRTY = {
    "name": "tickets_dirty.csv",
    "raw_records": 55,
    "accepted": 51,
    "quarantine": 3,
    "blank": 1,
    "segments": 2,
    "cells_total": 510,
    "cells_missing": 14,
    "cells_value": 496,
    "cells_ok": 494,
    "cells_format_bad": 2,
    "rows_unique": 50,
    "rows_dup": 1,
    "outlier_cells": 7,
    "tested_cells": 98,
    "score": "65.24",
    "grade": "C",
    "penalty_sum": "34.76",
}

DIRTY_PENALTIES = {
    "missing": ("0.0275", "0.3438", "10.31"),
    "duplicate": ("0.0196", "0.3267", "8.17"),
    "outlier": ("0.0714", "0.7140", "14.28"),
    "format": ("0.0040", "0.0800", "2.00"),
}

QUARANTINE = [(44, "Q_COLUMN_COUNT"), (45, "Q_COLUMN_COUNT"), (57, "Q_TRUNCATED_ROW")]

MISSING_RUNS = {
    "agent": (8, 11, 4),
    "region": (14, 17, 4),
}

MISSING_PATTERNS = {
    ("agent",): 3,
    ("first_response_min",): 3,
    ("region",): 3,
    ("agent", "region"): 2,
    ("satisfaction",): 1,
}

CO_MISSING = {("agent", "region"): 2}

DUPLICATE = {
    "unique_rows": 50,
    "duplicate_rows": 1,
    "hash_representative": 3,
    "hash_duplicate_lineno": 35,
    "key_repeat": "T-2026-000102",
    "conflict_key": "T-2026-000204",
    "conflict_linenos": [36, 37],
    "conflict_fields": ["satisfaction", "agent"],
}

OUTLIERS = {
    "first_response_min": {
        "tested": 47, "outliers": 6, "median": "25", "mad": "12.5",
        "spread": "12.5", "method": "mad",
    },
    "handle_hours": {
        "tested": 51, "outliers": 1, "median": "3", "mad": "1.25",
        "spread": "1.25", "method": "mad",
    },
    "satisfaction": {"tested": 0, "outliers": 0, "method": "degenerate",
                     "floor": "5"},
}

OUTLIER_Z = {
    (3, "1204.5"): "63.6458",
    (55, "1980.0"): "105.4918",
    (55, "9.50"): "3.5074",
}

CLEAN = {"name": "tickets_clean.csv", "accepted": 24, "cells_total": 240,
         "cells_missing": 0, "score": "100.00", "grade": "A"}

CONSTANT = {"name": "tickets_constant.csv", "accepted": 10, "cells_total": 100,
            "cells_missing": 10, "score": "70.00", "grade": "C",
            "missing_penalty": "30.00", "empty_column": "agent",
            "degenerate_column": "handle_hours"}

PROFILE_COLUMNS = {
    "ticket_id": {"missing": 0, "format_bad": 0, "distinct": 49},
    "customer_id": {"missing": 0, "format_bad": 0, "distinct": 49},
    "agent": {"missing": 5, "filled": 46, "fill_rate": "0.9020",
              "missing_rate": "0.0980"},
    "region": {"missing": 5, "filled": 46, "missing_rate": "0.0980"},
    "satisfaction": {"missing": 1, "format_bad": 1, "format_rate": "0.0200",
                     "filled": 50},
    "first_response_min": {"missing": 3, "format_bad": 1, "filled": 48,
                           "missing_rate": "0.0588", "min": "7.0",
                           "max": "1980.0"},
}
