export DBT_PROFILES_DIR := $(CURDIR)
DBT := uv run dbt
# Extra flags for the demos' `dbt show`. CI sets SHOW_FLAGS="--output json"
# to check the numbers (scripts/ci_check.py).
SHOW_FLAGS ?=

.PHONY: setup enterprise-up enterprise-check integration-config driver driver-build data deps debug seed load run test build snapshot incremental-demo snapshot-demo microbatch-demo adapter-tests docs docs-serve clean all

## One-time setup: configure the Enterprise connection, Python env, driver, data
setup: integration-config deps driver data

deps:
	uv sync
	$(DBT) deps

# The prebuilt driver from the pinned release (scripts/driver-version), or a
# build from source where there's none. driver-build always builds.
driver:
	./scripts/download_driver.sh

driver-build:
	./scripts/build_driver.sh

data:
	./scripts/download_data.sh

# Provision/verify the dedicated localhost Enterprise TLS cluster.
enterprise-up:
	python3 ../scripts/redis_enterprise.py up

enterprise-check:
	python3 ../scripts/redis_enterprise.py verify

# All live project and adapter checks require the Enterprise test connection.
integration-config:
	python3 ../scripts/integration_config.py

debug seed load run test build snapshot incremental-demo snapshot-demo microbatch-demo adapter-tests docs: integration-config

## dbt commands
debug:
	$(DBT) debug

seed:
	$(DBT) seed

# Load the raw trips CSV (every 50th row by default; override with ARGS, e.g.
# make load ARGS="--args '{sample_every: 10}'")
load:
	$(DBT) run-operation load_raw_trips $(ARGS)

run:
	$(DBT) run

test:
	$(DBT) test

build:
	$(DBT) build

snapshot:
	$(DBT) snapshot

# fct_trips with the first half of January, then an incremental run that
# reloads the last day and appends the rest.
# fct_trips (merge) and agg_zone_daily (delete+insert on a composite key):
# load the first half of January, then the rest. The zone-day totals always
# add up to the trips.
INCREMENTAL_DEMO_SQL = select (select count(*) from {{ ref('fct_trips') }}) as trips, (select max(pickup_datetime) from {{ ref('fct_trips') }}) as last_pickup, (select sum(trips) from {{ ref('agg_zone_daily') }}) as zone_day_trips, (select count(*) from {{ ref('agg_zone_daily') }}) as zone_days

incremental-demo:
	$(DBT) run -s +agg_zone_daily --full-refresh --vars '{trips_end: "2019-01-16 00:00:00"}'
	$(DBT) show $(SHOW_FLAGS) --inline "$(INCREMENTAL_DEMO_SQL)" --vars '{trips_end: "2019-01-16 00:00:00"}'
	$(DBT) run -s +agg_zone_daily
	$(DBT) show $(SHOW_FLAGS) --inline "$(INCREMENTAL_DEMO_SQL)"

# Snapshot the zone lookup, rename JFK, snapshot again: the history keeps
# both versions. `dbt seed` then restores the lookup (a third snapshot would
# record that too).
snapshot-demo:
	$(DBT) snapshot
	$(DBT) run-operation rename_zone --args '{location_id: 132, name: "JFK International Airport"}'
	$(DBT) snapshot
	$(DBT) show $(SHOW_FLAGS) --inline "select \"LocationID\", \"Zone\", dbt_valid_from, dbt_valid_to from {{ ref('zones_snapshot') }} where \"LocationID\" = 132 order by dbt_valid_from"
	$(DBT) seed

# fct_trips_microbatch: backfill Jan 1–3 as three daily batches (run in
# parallel), then re-run Jan 2 alone, which replaces only that day's rows.
microbatch-demo:
	$(DBT) run -s fct_trips_microbatch --vars '{microbatch_demo: true}' --full-refresh --event-time-start 2019-01-01 --event-time-end 2019-01-04
	$(DBT) run -s fct_trips_microbatch --vars '{microbatch_demo: true}' --event-time-start 2019-01-02 --event-time-end 2019-01-03
	$(DBT) show $(SHOW_FLAGS) --vars '{microbatch_demo: true}' --inline "select pickup_date, count(*) as trips from {{ ref('fct_trips_microbatch') }} group by pickup_date order by pickup_date"

# dbt's adapter test suite (adapter/tests/functional): each test class makes
# and drops its own schemas in REDIS_URI's database.
adapter-tests:
	uv run pytest -n 4

docs:
	$(DBT) docs generate

docs-serve: docs
	$(DBT) docs serve

clean:
	$(DBT) clean

## Everything, on a dedicated Redis Enterprise test cluster
all: debug seed load build docs
