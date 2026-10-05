import base64
import json
import os
import re
import urllib.error
import urllib.request


def settings(cfg):
    base = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    email, token = os.environ.get("JIRA_EMAIL"), os.environ.get("JIRA_API_TOKEN")
    project = os.environ.get("JIRA_PROJECT_KEY") or cfg.get("project_key")
    if not (base.startswith("https://") and email and token and project):
        return None
    return {"base": base, "email": email, "token": token, "project": project}


def configured(cfg):
    return settings(cfg) is not None


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build_fields(cfg, project, task):
    steps = "\n".join(f"* {a}" for a in task["actions"])
    description = (f"{task['why']}\n\nSuggested steps:\n{steps}\n\n"
                   f"Brand: {task['brand']}\nOwner function: {task['function']}\n"
                   f"Source: brand-ops scorecard ({task['key']})")
    fields = {
        "project": {"key": project},
        "summary": task["title"][:250],
        "description": description,
        "issuetype": {"name": cfg.get("issue_type", "Task")},
        "labels": ["brandops", "brandops-" + task["key"].replace(":", "-"), _slug(task["function"])],
    }
    if cfg.get("set_priority"):
        fields["priority"] = {"name": cfg.get("priority_map", {}).get(task["priority"], task["priority"])}
    return fields


def create_issue(cfg, task):
    s = settings(cfg)
    if s is None:
        raise RuntimeError("Jira is not configured")
    auth = base64.b64encode(f"{s['email']}:{s['token']}".encode()).decode()
    req = urllib.request.Request(
        f"{s['base']}/rest/api/2/issue",
        data=json.dumps({"fields": build_fields(cfg, s["project"], task)}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Basic " + auth},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)["key"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Jira returned {e.code}: {e.read().decode()[:300]}") from None
