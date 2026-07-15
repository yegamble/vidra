# Vidra meta-repo developer commands. Run `make help` for the list.
# Canonical environment/DX reference: .ralph/specs/environments.md

.DEFAULT_GOAL := help
SHELL := /bin/bash

ENV_FILE ?= env/local.env
IPFS_PUBLIC_GATEWAY_URL ?= https://ipfs.io

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

.PHONY: nuke
nuke: ## Stop the stack AND delete data volumes (fresh start)
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
