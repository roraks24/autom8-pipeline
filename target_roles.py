#!/usr/bin/env python3
"""
target_roles.py (Facade) - Centralized role matching and priority tier classification.

Forwards to modular package implementation in src.core.classifier.
STRICT POLICY: Internships only. Regular jobs are excluded across all platforms.
"""

from src.core.classifier import (
    EXCLUDE_PATTERNS,
    EXCLUDED_ROLES,
    INTERNSHIP_PATTERNS,
    SENIOR_PATTERNS,
    TARGET_ROLE_TIERS,
    TIER_1_PATTERNS,
    TIER_2_PATTERNS,
    TIER_3_PATTERNS,
    classify_role,
    is_internship,
    is_target_role,
)

__all__ = [
    "classify_role",
    "is_target_role",
    "is_internship",
    "INTERNSHIP_PATTERNS",
    "TIER_1_PATTERNS",
    "TIER_2_PATTERNS",
    "TIER_3_PATTERNS",
    "EXCLUDE_PATTERNS",
    "SENIOR_PATTERNS",
    "TARGET_ROLE_TIERS",
    "EXCLUDED_ROLES",
]
