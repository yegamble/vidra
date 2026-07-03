# Vidra meta-repo developer commands. Run `make help` for the list.
# Canonical environment/DX reference: .ralph/specs/environments.md

.DEFAULT_GOAL := help
SHELL := /bin/bash

ENV_FILE ?= env/local.env

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: bootstrap
bootstrap: ## Clone/update both sub-repos
	./bootstrap.sh

.PHONY: dev
dev: bootstrap ## Backend stack up (postgres+redis+migrate+api); run the frontend on the host for HMR
	docker compose --profile core up -d --build
	@echo ""
	@echo "Backend up. For frontend hot-reload development:"
	@echo "  cd vidra-user && npm ci && NEXT_PUBLIC_API_BASE_URL=http://localhost:$${HTTP_PORT:-8080} npm run dev"

.PHONY: up
up: bootstrap ## Full stack incl. the containerised frontend (:3000)
	docker compose --profile core --profile frontend up -d --build

.PHONY: down
down: ## Stop the stack (data volumes preserved)
	docker compose --profile core --profile frontend --profile storage down

.PHONY: nuke
nuke: ## Stop the stack AND delete data volumes (fresh start)
	docker compose --profile core --profile frontend --profile storage down -v

.PHONY: logs
logs: ## Tail all service logs
	docker compose --profile core --profile frontend logs -f --tail=100

.PHONY: test
test: ## Run both repos' canonical CI gates (backend needs the dockerised postgres/redis)
	cd vidra-core && $(MAKE) ci
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
