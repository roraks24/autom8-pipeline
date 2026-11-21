#!/usr/bin/env python3
"""
tailor.py (Facade) - ATS Resume Tailoring & PDF Generation Engine.

Forwards to modular package implementation in src.core.tailor.
"""

from src.config import RESUMES_DIR
from src.core.tailor import (
    PROJECTS_BANK,
    VERIFIED_SKILLS_REPOSITORY,
    ATSResumeTailor,
    generate_pdf,
    get_or_create_resume,
    render_html_template,
    tailor_resume_data,
)

__all__ = [
    "tailor_resume_data",
    "generate_pdf",
    "get_or_create_resume",
    "ATSResumeTailor",
    "render_html_template",
    "VERIFIED_SKILLS_REPOSITORY",
    "PROJECTS_BANK",
    "RESUMES_DIR",
]

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Tailor an ATS-friendly resume")
    parser.add_argument("--company", default="OpenAI", help="Target company")
    parser.add_argument("--title", default="AI Engineer", help="Target job title")
    parser.add_argument("--jd", default="", help="Job description text")
    args = parser.parse_args()

    get_or_create_resume(company=args.company, title=args.title, notes=args.jd)
