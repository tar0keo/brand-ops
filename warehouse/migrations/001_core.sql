create table brands (
  brand_id text primary key,
  name text not null,
  kind text not null,
  active boolean not null default true
);

-- Every connector writes this shape.
create table fact_metrics (
  id bigserial primary key,
  brand_id text not null references brands(brand_id),
  day date not null,
  source text not null,
  metric text not null,
  value double precision not null,
  dimensions jsonb not null default '{}',
  loaded_at timestamptz not null default now(),
  unique (brand_id, day, source, metric, dimensions)
);
create index on fact_metrics (brand_id, day);
create index on fact_metrics (metric, day);

-- Raw GEO prompt runs, kept so answers can be reviewed over time.
create table geo_runs (
  run_id bigserial primary key,
  brand_id text not null references brands(brand_id),
  prompt_id text not null,
  engine text not null,
  run_at timestamptz not null,
  mentioned boolean not null,
  linked boolean not null default false,
  position int,
  sentiment text,
  answer_text text,
  cited_sources jsonb not null default '[]'
);

create table sync_status (
  connector text primary key,
  last_success timestamptz,
  last_error text,
  rows_loaded int
);
