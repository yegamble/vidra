# Vidra meta-repo developer commands. Run `make help` for the list.
# Canonical environment/DX reference: .ralph/specs/environments.md

.DEFAULT_GOAL := help
SHELL := /bin/bash

ENV_FILE ?= env/local.env
IPFS_PUBLIC_GATEWAY_URL ?= https://ipfs.io

# Production targets operate on a DIFFERENT env file and a DIFFERENT compose
# chain from every dev target above; nothing below can touch a local stack by
# accident. Override with `make deploy PROD_ENV_FILE=env/staging.env`.
PROD_ENV_FILE ?= env/production.env

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: bootstrap
bootstrap: ## Clone/update both sub-repos
	./bootstrap.sh

.PHONY: dev
dev: bootstrap ## Backend + search stack up (postgres+redis+migrate+api+search); run the frontend on the host for HMR
	docker compose --profile core up -d --build
	@echo ""
	@echo "Backend up:"
	@echo "  api      http://localhost:$${HTTP_PORT:-8080}"
	@echo "  search   http://localhost:$${SEARCH_HTTP_PORT:-8081}   (internal service; core calls it over the compose network)"
	@echo "For frontend hot-reload development:"
	@echo "  cd vidra-user && npm ci && NEXT_PUBLIC_API_BASE_URL=http://localhost:$${HTTP_PORT:-8080} npm run dev"

.PHONY: up
up: bootstrap ## Full stack incl. the containerised frontend (:3000)
	docker compose --profile core --profile frontend up -d --build

.PHONY: ipfs-live
ipfs-live: bootstrap ## Core stack + live public IPFS mirror + separate private mirror
	IPFS_ENABLED=true IPFS_PUBLIC_NETWORK=true \
		IPFS_GATEWAY_URL="$(IPFS_PUBLIC_GATEWAY_URL)" IPFS_MIRROR_PRIVATE=true \
		docker compose --profile core --profile ipfs --profile ipfs-private up -d --build
	@echo ""
	@echo "IPFS live mode enabled:"
	@echo "  public provider  http://localhost:$${IPFS_API_PORT:-5001} (RPC; loopback only)"
	@echo "  public gateway   $(IPFS_PUBLIC_GATEWAY_URL) (emitted in video API responses)"
	@echo "  private mirror   http://localhost:$${IPFS_PRIVATE_API_PORT:-5002} (RPC; loopback only)"
	@echo "WARNING: public CIDs may remain retrievable after this node unpins them."

# Dev hot-reload overlay: air-rebuilt Go api + next dev HMR frontend, both with
# bind-mounted source so code changes reflect WITHOUT down+rebuild. Applied on
# top of the base compose via -f docker-compose.dev.yml (see that file). The
# explicit -f chain disables auto-loading of docker-compose.override.yml, so it is
# passed explicitly (it carries the api's SEARCH_SERVICE_URL/SEARCH_INTERNAL_SECRET).
DEV_HOT_COMPOSE := docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.dev.yml

.PHONY: dev-hot
dev-hot: bootstrap ## Full stack with hot reload: air-rebuilt Go api (:8080) + next dev HMR frontend (:3000)
	$(DEV_HOT_COMPOSE) --profile core --profile frontend up -d --build
	@echo ""
	@echo "Hot-reload stack up:"
	@echo "  api      http://localhost:$${HTTP_PORT:-8080}   (edit vidra-core/**/*.go -> air rebuilds)"
	@echo "  search   http://localhost:$${SEARCH_HTTP_PORT:-8081}   (edit vidra-search/**/*.go -> air rebuilds)"
	@echo "  frontend http://localhost:$${FRONTEND_PORT:-3000} (edit vidra-user/** -> HMR)"
	@echo "First run is slow: go mod download + cold compile, npm volume seed. Watch: make dev-hot-logs"

.PHONY: dev-hot-down
dev-hot-down: ## Stop the hot-reload stack (db data + go/npm cache volumes preserved)
	$(DEV_HOT_COMPOSE) --profile core --profile frontend --profile storage down

.PHONY: dev-hot-logs
dev-hot-logs: ## Tail hot-reload stack logs
	$(DEV_HOT_COMPOSE) --profile core --profile frontend logs -f --tail=100

.PHONY: dev-hot-nuke
dev-hot-nuke: ## Stop hot-reload stack AND delete ALL volumes (db data + go/npm caches)
	$(DEV_HOT_COMPOSE) --profile core --profile frontend --profile storage down -v

.PHONY: down
down: ## Stop the stack (data volumes preserved)
	docker compose --profile core --profile frontend --profile storage down

# `nuke` is one character away from `down` and it deletes postgres_data — every
# account, video row and moderation decision on the machine. The guard makes the
# destructive variant impossible to reach by typo: it needs either CONFIRM=1 or
# the word "nuke" typed at an interactive prompt, and it refuses outright when
# there is no terminal (CI, a script, an editor task runner).
.PHONY: nuke
nuke: ## Stop the stack AND delete data volumes (fresh start) — needs CONFIRM=1
	@if [ "$(CONFIRM)" = "1" ]; then \
		echo "CONFIRM=1 given — proceeding."; \
	elif [ -t 0 ]; then \
		echo "This DELETES all local data volumes (postgres_data, media, caches)."; \
		read -r -p 'Type "nuke" to confirm: ' answer; \
		[ "$$answer" = "nuke" ] || { echo "Aborted."; exit 1; }; \
	else \
		echo "Refusing: 'make nuke' deletes all local data volumes."; \
		echo "Re-run interactively, or pass CONFIRM=1 if you really mean it."; \
		exit 1; \
	fi
	docker compose --profile core --profile frontend --profile storage down -v

.PHONY: logs
logs: ## Tail all service logs
	docker compose --profile core --profile frontend logs -f --tail=100

.PHONY: test
test: ## Run all three repos' canonical CI gates (backend/search need the dockerised postgres/redis)
	cd vidra-core && $(MAKE) ci
	cd vidra-search && $(MAKE) ci
	cd vidra-user && npm run ci

.PHONY: e2e-backed
e2e-backed: ## Run the backend-backed Playwright suite against a fresh dockerised stack
	cd vidra-core && docker compose --profile core down -v && \
		RATE_LIMIT_ENABLED=false HTTP_IMPORT_ALLOW_PRIVATE_URLS=true \
		DEV_MAIL_CAPTURE_ENABLED=true LIVE_INGEST_SECRET=e2e-ingest-secret \
		TRANSCODING_ENABLED=true CORS_ALLOWED_ORIGINS=http://localhost:3000 \
		docker compose --profile core up -d --build
	cd vidra-user && NEXT_PUBLIC_API_BASE_URL=http://localhost:$${HTTP_PORT:-8080} npm run build && \
		E2E_API_URL=http://localhost:$${HTTP_PORT:-8080} npm run e2e:backed

.PHONY: seed
seed: ## Seed a demo account + channel against the running local api
	./scripts/seed.sh

.PHONY: env-check
env-check: ## Show which env template the compose commands would use
	@echo "ENV_FILE=$(ENV_FILE)"; test -f $(ENV_FILE) && echo "exists" || echo "missing — copy env/<env>.env.example"

# ---------------------------------------------------------------------------
# Production / staging operations. Thin wrappers over deploy/*.sh so the runbook
# and muscle memory agree; every script works standalone too. The compose-based
# ones all use the explicit -f chain (base + prod overlay), which deliberately
# DISABLES auto-loading of docker-compose.override.yml — that file carries dev
# defaults such as RATE_LIMIT_ENABLED=false. See deploy/README.md.
# ---------------------------------------------------------------------------

# The one prod target that touches GitHub rather than this host: it cuts the
# releases that BUILD the images every other target here pulls. Publishing is
# outward-facing and a release is not meant to be deleted, so release.sh asks
# before it publishes. Same CONFIRM=1 convention as `nuke`/`restore`: CONFIRM=1
# answers that prompt in advance (it passes --yes); without it the script
# prompts, and refuses outright when there is no terminal.
.PHONY: release
release: ## Cut a release + GHCR images in all three repos: make release VERSION=v0.2.0 [REPOS="vidra-core"]
	@test -n "$(VERSION)" || { echo "usage: make release VERSION=v0.2.0 [REPOS=\"vidra-core vidra-search\"] [CONFIRM=1]"; exit 1; }
	./deploy/release.sh $(if $(filter 1,$(CONFIRM)),--yes) $(VERSION) $(REPOS)

# Delegated, NOT re-spelled. This used to be a literal `docker compose -f ... -f
# ... --profile core --profile frontend`, i.e. a fifth copy of a chain that
# deploy/lib.sh now owns — and it had already drifted: it hardcoded the two
# profiles (so an env file with EXTRA_COMPOSE_PROFILES=ipfs was validated
# without ipfs) and applied neither external-datastore overlay (so an operator
# on managed Postgres got "renders cleanly" for a render containing the BUNDLED
# postgres). deploy/compose.sh reads the shape out of $(PROD_ENV_FILE), exactly
# as the deploy scripts do.
PROD_COMPOSE := ENV_FILE=$(PROD_ENV_FILE) ./deploy/compose.sh

.PHONY: prod-config
prod-config: ## Render+validate the production compose chain (catches missing required vars)
	$(PROD_COMPOSE) config -q && echo "OK: $(PROD_ENV_FILE) renders cleanly"

.PHONY: deploy
deploy: ## Deploy the tags pinned in PROD_ENV_FILE: dump -> pull -> gated migrate -> up -> probe
	ENV_FILE=$(PROD_ENV_FILE) ./deploy/deploy.sh

.PHONY: rollback
rollback: ## Roll the app back to a released tag: make rollback TAG=v0.1.0
	@test -n "$(TAG)" || { echo "usage: make rollback TAG=v0.1.0"; exit 1; }
	ENV_FILE=$(PROD_ENV_FILE) ./deploy/rollback.sh $(TAG)

.PHONY: backup
backup: ## Take a database dump now (same script the systemd timer runs)
	ENV_FILE=$(PROD_ENV_FILE) ./deploy/backup.sh

# restore.sh refuses to run without --yes or RESTORE_CONFIRM=<db name>, and that
# refusal is the whole point of the script — so the target has to supply the
# confirmation itself, and therefore has to ask for one first. Same convention as
# `make nuke`: CONFIRM=1, or the word typed at an interactive prompt, and a flat
# refusal when there is no terminal.
.PHONY: restore
restore: ## DESTRUCTIVE. Restore a dump: make restore DUMP=backups/vidra-<ts>.dump.gz — needs CONFIRM=1
	@test -n "$(DUMP)" || { echo "usage: make restore DUMP=backups/vidra-<ts>.dump.gz CONFIRM=1"; exit 1; }
	@test -f "$(DUMP)" || { echo "dump not found: $(DUMP)"; exit 1; }
	@if [ "$(CONFIRM)" = "1" ]; then \
		echo "CONFIRM=1 given — proceeding."; \
	elif [ -t 0 ]; then \
		echo "This DROPS the database of the stack described by $(PROD_ENV_FILE)"; \
		echo "and replaces it with $(DUMP). Everything written since is lost."; \
		read -r -p 'Type "restore" to confirm: ' answer; \
		[ "$$answer" = "restore" ] || { echo "Aborted."; exit 1; }; \
	else \
		echo "Refusing: 'make restore' drops and recreates the $(PROD_ENV_FILE) database."; \
		echo "Re-run interactively, or pass CONFIRM=1 if you really mean it."; \
		exit 1; \
	fi
	ENV_FILE=$(PROD_ENV_FILE) ./deploy/restore.sh --yes $(DUMP)

.PHONY: prod-logs
prod-logs: ## Tail production stack logs
	$(PROD_COMPOSE) logs -f --tail=100

.PHONY: prod-down
prod-down: ## Stop the production stack (data volumes preserved)
	$(PROD_COMPOSE) down
