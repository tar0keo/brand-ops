# Turning scorecard results into Jira tasks

The Actions view checks every brand against the limits in `config/task_rules.yaml` and proposes tasks with the evidence, an owner function, a priority, and suggested steps. The rules are deterministic, so the same numbers always give the same tasks.

## Three ways to use it

1. **Review only.** Open the Actions tab and read the proposals.
2. **CSV import (no API key).** Click "Download CSV for Jira import", then use Jira's CSV importer (Settings, System, External System Import). Map Summary, Description, Issue Type, Priority, and the three Labels columns.
3. **Direct creation.** Set these variables (see `.env.example`) and restart the server:
   - `JIRA_BASE_URL` (must be https, for example https://your-team.atlassian.net)
   - `JIRA_EMAIL` and `JIRA_API_TOKEN` (create a token under your Atlassian account security settings)
   - `JIRA_PROJECT_KEY` (or set `project_key` in the config)

   Then tick tasks and click "Create selected tasks".

## Behaviour

- **No duplicates.** Each task has a stable key (rule and brand). Once ticketed, it isn't proposed again for `cooldown_days` (14 by default). The record lives in the `task_log` table, which the app creates on first use.
- **Demo mode never reaches Jira.** With `--demo`, creating tasks is simulated and returns DEMO-n keys, even if Jira variables are set.
- **Labels.** Every issue gets `brandops`, a key label such as `brandops-roas_low-fla`, and an owner label such as `media-buying`, so you can filter and build boards.
- **Priority.** It is written into the description. To also set Jira's Priority field, set `set_priority: true`, but only if Priority is on your project's create screen, or Jira will reject the issue.
- **Issue type** must exist in your project. Change `issue_type` if yours isn't "Task".

## Tuning

Edit `config/task_rules.yaml`. Raise `min_spend` and `min_reviews` to cut noise from small brands, and agree each limit with the function that owns it.
