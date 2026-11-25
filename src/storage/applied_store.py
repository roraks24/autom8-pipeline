import datetime
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import ACTIVE_PLATFORMS, APPLIED_DB_PATH, SKIPPED_CACHE_PATH


def normalize_url(url: str) -> str:
    """Normalizes a job URL for reliable deduplication."""
    if not url:
        return ""
    u = url.strip()
    if "gh_jid=" not in u:
        u = u.split("?")[0]
    return u.rstrip("/").lower()


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    """Writes JSON atomically via a temporary file to prevent corruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, path)


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _today_str() -> str:
    return datetime.date.today().isoformat()


def _extract_application_id(notes: str, explicit_id: Optional[str] = None) -> Optional[str]:
    if explicit_id:
        return str(explicit_id).strip()
    if not notes:
        return None
    m = re.search(r"Application ID:\s*([A-Za-z0-9_-]+)", notes, re.I)
    return m.group(1) if m else None


class AppliedJobsStore:
    """
    Single JSON Database for all submitted job applications (data/applied_jobs.json).
    Provides atomic writes, deduplication, daily quota tracking, and analytics.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.path = Path(db_path) if db_path else APPLIED_DB_PATH
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        default = {
            "schema_version": "2.0",
            "updated_at": _now_iso(),
            "total_applied": 0,
            "by_platform": {},
            "jobs": [],
        }
        data = _read_json(self.path, default)
        if not isinstance(data.get("jobs"), list):
            data["jobs"] = []
        return data

    def reload(self) -> None:
        """Reloads JSON state from disk."""
        self._data = self._load()

    def _recompute_summary(self) -> None:
        by_plat: Dict[str, int] = {}
        for job in self._data["jobs"]:
            src = (job.get("source") or "unknown").lower()
            by_plat[src] = by_plat.get(src, 0) + 1
        self._data["total_applied"] = len(self._data["jobs"])
        self._data["by_platform"] = dict(sorted(by_plat.items()))
        self._data["updated_at"] = _now_iso()

    def _save(self) -> None:
        self._recompute_summary()
        _write_json_atomic(self.path, self._data)

    def has_applied(
        self,
        url: str = "",
        job_id: str = "",
        company: str = "",
        title: str = "",
    ) -> bool:
        """Checks whether a job has already been applied to."""
        norm_u = normalize_url(url)
        clean_id = (job_id or "").strip().lower()
        clean_comp = (company or "").strip().lower()
        clean_title = (title or "").strip().lower()

        for job in self._data["jobs"]:
            if norm_u and normalize_url(job.get("url", "")) == norm_u:
                return True
            if clean_id and (job.get("id") or "").strip().lower() == clean_id:
                return True
            if (
                clean_comp
                and clean_title
                and clean_comp not in ("company", "startup", "unknown")
                and (job.get("company") or "").strip().lower() == clean_comp
                and (job.get("title") or "").strip().lower() == clean_title
            ):
                return True
        return False

    def record_applied(self, record: Dict[str, Any], flush: bool = True) -> Dict[str, Any]:
        """Inserts or enriches an applied job record cleanly with URL deduplication."""
        norm_u = normalize_url(record.get("url", ""))
        clean_id = (record.get("id") or "").strip()
        source = (record.get("source") or "unknown").lower().strip()
        notes = record.get("notes") or ""
        notes_clean = re.sub(r";\s*App status:.*$", "", str(notes), flags=re.I).strip()

        entry = {
            "id": clean_id or f"{source}:{abs(hash(norm_u or record.get('company', '')))}",
            "source": source,
            "company": (record.get("company") or "Company").strip(),
            "title": (record.get("title") or "AI Engineer").strip(),
            "location": (record.get("location") or "Remote / India").strip(),
            "url": (record.get("url") or "").strip(),
            "applied_at": record.get("applied_at") or _today_str(),
            "application_id": _extract_application_id(notes_clean, record.get("application_id")),
            "salary": (record.get("salary") or "").strip() or None,
            "target_tier": record.get("target_tier"),
            "target_category": record.get("target_category"),
            "skills": (record.get("skills") or "").strip() or None,
            "tailored_resume": (record.get("tailored_resume") or "").strip() or None,
            "notes": notes_clean or None,
        }

        existing_idx = None
        for idx, job in enumerate(self._data["jobs"]):
            if (norm_u and normalize_url(job.get("url", "")) == norm_u) or (
                clean_id and job.get("id") == clean_id
            ):
                existing_idx = idx
                break

        if existing_idx is not None:
            prev = self._data["jobs"][existing_idx]
            merged = dict(prev)
            for k, v in entry.items():
                if v is not None and (k not in merged or merged[k] is None or k in ("tailored_resume", "application_id", "applied_at")):
                    merged[k] = v
            self._data["jobs"][existing_idx] = merged
            result = merged
        else:
            self._data["jobs"].append(entry)
            result = entry

        if flush:
            self._save()
        return result

    def save_batch(self) -> None:
        self._save()

    def update_outcome(
        self,
        application_id: Optional[str] = None,
        url: str = "",
        outcome: str = "",
        company: str = "",
        title: str = "",
        source: str = "internshala",
        vha_score: Optional[int] = None,
        has_assignment: bool = False,
        has_interview: bool = False,
        flush: bool = True,
    ) -> bool:
        """Updates an existing applied job's hiring outcome (Seen, In-touch, Shortlisted, Not Selected).

        Matches by application_id first, then normalized URL, then exact (source, company, title).
        Backfills application_id when previously null. Returns True if the stored record changed.
        """
        clean_outcome = (outcome or "").strip()
        if not clean_outcome:
            return False

        clean_app_id = str(application_id).strip() if application_id not in (None, "") else ""
        norm_u = normalize_url(url)
        clean_comp = (company or "").strip().lower()
        clean_title = (title or "").strip().lower()
        src_low = (source or "").lower().strip()

        target_job = None
        for job in reversed(self._data["jobs"]):
            if src_low and (job.get("source") or "").lower() != src_low:
                continue
            existing_app_id = str(job.get("application_id") or "").strip()
            if clean_app_id and existing_app_id and existing_app_id == clean_app_id:
                target_job = job
                break
            if norm_u and normalize_url(job.get("url", "")) == norm_u:
                target_job = job
                break
            if (
                clean_comp
                and clean_title
                and clean_comp not in ("company", "startup", "unknown")
                and (job.get("company") or "").strip().lower() == clean_comp
                and (job.get("title") or "").strip().lower() == clean_title
            ):
                target_job = job
                break

        if target_job is None:
            return False

        changed = False
        if target_job.get("outcome") != clean_outcome:
            target_job["outcome"] = clean_outcome
            target_job["outcome_updated_at"] = _now_iso()
            changed = True
        if clean_app_id and not target_job.get("application_id"):
            target_job["application_id"] = clean_app_id
            changed = True
        if vha_score is not None and target_job.get("vha_score") != vha_score:
            target_job["vha_score"] = vha_score
            changed = True
        if has_assignment and not target_job.get("has_assignment"):
            target_job["has_assignment"] = True
            changed = True
        if has_interview and not target_job.get("has_interview"):
            target_job["has_interview"] = True
            changed = True

        if changed and flush:
            self._save()
        return changed

    def get_all(
        self,
        source: Optional[str] = None,
        tier: Optional[int] = None,
        date_str: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Returns applied jobs newest-first, optionally filtered."""
        results = list(reversed(self._data["jobs"]))
        if source:
            src_low = source.lower().strip()
            results = [j for j in results if (j.get("source") or "").lower() == src_low]
        if tier is not None:
            results = [j for j in results if j.get("target_tier") == tier]
        if date_str:
            results = [j for j in results if str(j.get("applied_at") or "").startswith(date_str)]
        if limit is not None:
            results = results[:limit]
        return results

    def get_applied_today(self, source: Optional[str] = None, date_str: Optional[str] = None) -> List[Dict[str, Any]]:
        target_date = date_str or _today_str()
        return self.get_all(source=source, date_str=target_date)

    def get_stats(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        target_date = date_str or _today_str()
        self._recompute_summary()
        tier_counts: Dict[int, int] = {}
        outcome_counts: Dict[str, int] = {}
        today_by_platform: Dict[str, int] = {p: 0 for p in ACTIVE_PLATFORMS}

        for job in self._data["jobs"]:
            t = job.get("target_tier")
            if t is not None:
                tier_counts[t] = tier_counts.get(t, 0) + 1
            out = job.get("outcome")
            if out:
                outcome_counts[out] = outcome_counts.get(out, 0) + 1
            if str(job.get("applied_at") or "").startswith(target_date):
                src = (job.get("source") or "unknown").lower()
                today_by_platform[src] = today_by_platform.get(src, 0) + 1

        return {
            "total_applied": self._data["total_applied"],
            "by_platform": self._data["by_platform"],
            "today_date": target_date,
            "today_by_platform": today_by_platform,
            "today_total": sum(today_by_platform.values()),
            "tier_counts": tier_counts,
            "outcome_counts": outcome_counts,
            "updated_at": self._data.get("updated_at"),
            "db_path": str(self.path),
        }


class SkippedCacheStore:
    """
    Lightweight JSON skip-cache storing expired, unpaid, ineligible, rejected,
    non-target, and already_applied URLs so discovery avoids redundant checks.
    """

    def __init__(self, cache_path: Optional[Path] = None):
        self.path = Path(cache_path) if cache_path else SKIPPED_CACHE_PATH
        self._data: Dict[str, Any] = self._load()
        self._id_index: Dict[str, str] = {}
        self._rebuild_index()

    def _load(self) -> Dict[str, Any]:
        default = {"updated_at": _now_iso(), "entries": {}}
        data = _read_json(self.path, default)
        if not isinstance(data.get("entries"), dict):
            data["entries"] = {}
        return data

    def reload(self) -> None:
        self._data = self._load()
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._id_index = {}
        for key, item in self._data["entries"].items():
            jid = (item.get("id") or "").strip().lower()
            if jid:
                self._id_index[jid] = key

    def _key_for(self, url: str = "", job_id: str = "") -> str:
        norm_u = normalize_url(url)
        if norm_u:
            return norm_u
        return (job_id or "").strip().lower()

    def is_skipped(self, url: str = "", job_id: str = "") -> bool:
        return self.get_status(url=url, job_id=job_id) is not None

    def get_status(self, url: str = "", job_id: str = "") -> Optional[str]:
        norm_u = normalize_url(url)
        if norm_u and norm_u in self._data["entries"]:
            return self._data["entries"][norm_u].get("status")
        clean_id = (job_id or "").strip().lower()
        if clean_id:
            if clean_id in self._data["entries"]:
                return self._data["entries"][clean_id].get("status")
            mapped_key = self._id_index.get(clean_id)
            if mapped_key and mapped_key in self._data["entries"]:
                return self._data["entries"][mapped_key].get("status")
        return None

    def record_skipped(
        self,
        url: str = "",
        job_id: str = "",
        source: str = "",
        company: str = "",
        title: str = "",
        status: str = "rejected",
        reason: str = "",
        flush: bool = True,
    ) -> None:
        key = self._key_for(url=url, job_id=job_id)
        if not key:
            return
        entry = {
            "id": (job_id or "").strip() or None,
            "source": (source or "").lower().strip() or None,
            "company": (company or "").strip() or None,
            "title": (title or "").strip() or None,
            "status": status,
            "reason": (reason or "")[:300] or None,
            "cached_at": _today_str(),
        }
        self._data["entries"][key] = entry
        if entry["id"]:
            self._id_index[entry["id"].lower()] = key
        if flush:
            self.save()

    def save(self) -> None:
        self._data["updated_at"] = _now_iso()
        _write_json_atomic(self.path, self._data)

    def get_stats(self) -> Dict[str, Any]:
        by_status: Dict[str, int] = {}
        for item in self._data["entries"].values():
            st = item.get("status") or "unknown"
            by_status[st] = by_status.get(st, 0) + 1
        return {
            "total_skipped": len(self._data["entries"]),
            "by_status": dict(sorted(by_status.items(), key=lambda x: -x[1])),
            "cache_path": str(self.path),
        }


def is_known_job(
    applied_store: AppliedJobsStore,
    skipped_store: SkippedCacheStore,
    url: str = "",
    job_id: str = "",
    company: str = "",
    title: str = "",
) -> Tuple[bool, Optional[str]]:
    """Checks both the single Applied JSON DB and Skipped Cache."""
    if applied_store.has_applied(url=url, job_id=job_id, company=company, title=title):
        return True, "applied"
    skip_status = skipped_store.get_status(url=url, job_id=job_id)
    if skip_status:
        return True, skip_status
    return False, None
