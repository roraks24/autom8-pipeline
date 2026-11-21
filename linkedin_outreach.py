#!/usr/bin/env python3
"""
linkedin_outreach.py (Facade) - Safe Recruiter & Founder Outreach Generator.

Forwards to modular package implementation in src.outreach.linkedin.
"""

from src.outreach.linkedin import (
    build_html_dashboard,
    build_markdown_report,
    generate_outreach_targets,
    main,
    run_linkedin_outreach,
)

__all__ = [
    "generate_outreach_targets",
    "build_markdown_report",
    "build_html_dashboard",
    "run_linkedin_outreach",
    "main",
]

if __name__ == "__main__":
    main()
