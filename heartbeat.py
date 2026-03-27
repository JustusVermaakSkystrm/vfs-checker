#!/usr/bin/env python3
"""
VFS Checker - Heartbeat / Status Email
=======================================
Runs every 4 hours via GitHub Actions.
Queries the GitHub API for recent checker activity and sends
a short status summary email so you know the system is alive.
"""

import os
import sys
import json
import smtplib
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Credentials from GitHub Secrets / environment ──────────────────────────
GMAIL_ADDRESS      = os.environ.get("GMAIL_ADDRESS", "trintruf@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")   # auto-provided by Actions
GITHUB_REPO        = os.environ.get("GITHUB_REPOSITORY", "JustusVermaakSkystrm/vfs-checker")

HOURS_BACK = 4   # How many hours of history to summarise
VFS_URL    = "https://visa.vfsglobal.com/gbr/en/ita/book-an-appointment"


# ── GitHub API helper ──────────────────────────────────────────────────────

def gh_get(path):
    """Make an authenticated GET request to the GitHub API."""
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"GitHub API error: {e}")
        return None


# ── Fetch recent run stats ─────────────────────────────────────────────────

def get_recent_stats():
    """
    Returns a dict summarising checker runs in the last HOURS_BACK hours.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    data = gh_get(f"/repos/{GITHUB_REPO}/actions/workflows/check_appointments.yml/runs"
                  f"?per_page=100&created=>={since_str}")

    stats = {
        "total": 0,
        "success": 0,
        "failure": 0,
        "slots_found": 0,
        "last_run": None,
        "last_status": "unknown",
    }

    if not data or "workflow_runs" not in data:
        return stats

    runs = [
        r for r in data["workflow_runs"]
        if r.get("created_at", "") >= since_str
    ]

    stats["total"] = len(runs)

    for run in runs:
        conclusion = run.get("conclusion", "")
        if conclusion == "success":
            stats["success"] += 1
        elif conclusion in ("failure", "timed_out"):
            stats["failure"] += 1
        # exit code 2 = slots found (we set continue-on-error so it still
        # shows as "success" at the workflow level — we rely on email alerts
        # for that case)

    if runs:
        latest = sorted(runs, key=lambda r: r.get("updated_at", ""), reverse=True)[0]
        stats["last_run"]    = latest.get("updated_at", "")
        stats["last_status"] = latest.get("conclusion", "in_progress")

    return stats


# ── Email ──────────────────────────────────────────────────────────────────

def send_heartbeat_email(stats):
    if not GMAIL_APP_PASSWORD:
        print("GMAIL_APP_PASSWORD not set. Cannot send heartbeat email.")
        return False

    now_utc  = datetime.now(timezone.utc)
    now_str  = now_utc.strftime("%A %d %b %Y, %H:%M UTC")
    since_str = (now_utc - timedelta(hours=HOURS_BACK)).strftime("%H:%M UTC")

    # Status icon
    if stats["failure"] == 0:
        health_icon = "OK"
        health_line = "All checks completed successfully."
    elif stats["failure"] < stats["total"] // 2:
        health_icon = "WARNING"
        health_line = f"{stats['failure']} check(s) failed — may be a temporary glitch."
    else:
        health_icon  = "ATTENTION"
        health_line  = f"{stats['failure']} out of {stats['total']} checks failed. Please investigate."

    last_run_str = "N/A"
    if stats["last_run"]:
        try:
            dt = datetime.fromisoformat(stats["last_run"].replace("Z", "+00:00"))
            last_run_str = dt.strftime("%H:%M UTC")
        except Exception:
            last_run_str = stats["last_run"]

    subject = f"[{health_icon}] VFS Checker Heartbeat - {now_str}"

    body = f"""VFS London Appointment Checker - Status Report
{'=' * 50}
Report time : {now_str}
Period      : Last {HOURS_BACK} hours (since {since_str})

SUMMARY
-------
Total checks run  : {stats['total']}
Successful        : {stats['success']}
Failed            : {stats['failure']}
Last check at     : {last_run_str}
Last check status : {stats['last_status'].upper()}

HEALTH STATUS: {health_icon}
{health_line}

WHAT THIS MEANS
---------------
- The checker is running automatically every ~5 minutes on GitHub.
- If you had received a separate "VFS APPOINTMENT AVAILABLE" email
  in the last {HOURS_BACK} hours, a slot was found.
- No such email = no slots have appeared yet. Keep waiting!

Monitor live at:
https://github.com/{GITHUB_REPO}/actions

Book your appointment at:
{VFS_URL}

-- VFS Checker Heartbeat (GitHub Actions)
"""

    try:
        msg = MIMEMultipart()
        msg["From"]    = GMAIL_ADDRESS
        msg["To"]      = GMAIL_ADDRESS
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)

        print(f"Heartbeat email sent to {GMAIL_ADDRESS}")
        return True

    except smtplib.SMTPAuthenticationError:
        print("Email auth failed. Check GMAIL_APP_PASSWORD secret.")
        return False
    except Exception as e:
        print(f"Email failed: {e}")
        return False


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("VFS Checker - Heartbeat")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 50)

    print(f"Fetching last {HOURS_BACK} hours of checker activity...")
    stats = get_recent_stats()

    print(f"Runs in last {HOURS_BACK}h: {stats['total']} total, "
          f"{stats['success']} ok, {stats['failure']} failed")

    send_heartbeat_email(stats)
    print("Done.")


if __name__ == "__main__":
    main()
