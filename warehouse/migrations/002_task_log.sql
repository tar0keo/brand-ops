-- Remembers which proposed tasks already became tickets. The app also creates this on first use.
create table if not exists task_log (
  task_key text primary key,
  jira_key text not null,
  created_at timestamptz not null default now()
);
