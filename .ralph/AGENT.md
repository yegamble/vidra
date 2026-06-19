# Agent Build Instructions — vidra-core (Go backend)

This checkout is **vidra-core**: a Go service (Echo) exposing the Vidra HTTP API.
The Next.js frontend lives in a separate `vidra-user` repo.

## Toolchain
- Go 1.26+
- Docker + Docker Compose
- Optional CLIs: `sqlc` (codegen), `migrate` (golang-migrate v4.17.1)

## Project Setup
```bash
cp .env.example .env        # safe local defaults (Compose service addresses)
go mod download
```

## Common Commands (Makefile — run `make help`)
```bash
make check        # fmt + vet + unit tests (fast local gate)
make test         # unit tests
make test-race    # tests with race detector
make cover        # coverage summary
make build        # build ./bin/api
make run          # run API locally (needs Postgres + Redis)
make up           # full Docker stack: postgres, redis, migrate, api
make down         # stop the Docker stack
make sqlc         # generate typed query code (requires sqlc)
make migrate-up   # apply migrations to DATABASE_URL (requires migrate CLI)
```

## Running the full stack
```bash
make up
# then:
curl localhost:8080/healthz          # {"status":"ok"}
curl localhost:8080/readyz           # components: postgres/redis
curl localhost:8080/api/v1/nodeinfo  # instance discovery metadata
```

## Layout
- `cmd/api` — entrypoint + graceful shutdown
- `internal/config` — env config (only place that reads env)
- `internal/httpapi` — Echo handlers/routing/middleware
- `internal/store` — pgx pool + sqlc queries (`queries/`, generated `sqlcgen/`)
- `internal/cache` — Redis client
- `migrations` — golang-migrate numbered pairs

## Key Learnings
- sqlc reads `migrations/` as its schema; keep migrations and queries in sync.
- `internal/store/sqlcgen` is generated, not committed-by-hand. No code imports
  it yet, so the module compiles before `sqlc generate` is run.
- Liveness (`/healthz`) does NO dependency checks; readiness (`/readyz`) pings
  Postgres + Redis and returns 503 if any is down.

## Feature Development Quality Standards

**CRITICAL**: All new features MUST meet the following mandatory requirements before being considered complete.

### Testing Requirements

- **Minimum Coverage**: 85% code coverage ratio required for all new code
- **Test Pass Rate**: 100% - all tests must pass, no exceptions
- **Test Types Required**:
  - Unit tests for all business logic and services
  - Integration tests for API endpoints or main functionality
  - End-to-end tests for critical user workflows
- **Coverage Validation**: Run coverage reports before marking features complete:
  ```bash
  # Examples by language/framework
  npm run test:coverage
  pytest --cov=src tests/ --cov-report=term-missing
  cargo tarpaulin --out Html
  ```
- **Test Quality**: Tests must validate behavior, not just achieve coverage metrics
- **Test Documentation**: Complex test scenarios must include comments explaining the test strategy

### Git Workflow Requirements

Before moving to the next feature, ALL changes must be:

1. **Committed with Clear Messages**:
   ```bash
   git add .
   git commit -m "feat(module): descriptive message following conventional commits"
   ```
   - Use conventional commit format: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, etc.
   - Include scope when applicable: `feat(api):`, `fix(ui):`, `test(auth):`
   - Write descriptive messages that explain WHAT changed and WHY

2. **Pushed to Remote Repository**:
   ```bash
   git push origin <branch-name>
   ```
   - Never leave completed features uncommitted
   - Push regularly to maintain backup and enable collaboration
   - Ensure CI/CD pipelines pass before considering feature complete

3. **Branch Hygiene**:
   - Work on feature branches, never directly on `main`
   - Branch naming convention: `feature/<feature-name>`, `fix/<issue-name>`, `docs/<doc-update>`
   - Create pull requests for all significant changes

4. **Ralph Integration**:
   - Update .ralph/fix_plan.md with new tasks before starting work
   - Mark items complete in .ralph/fix_plan.md upon completion
   - Update .ralph/PROMPT.md if development patterns change
   - Test features work within Ralph's autonomous loop

### Documentation Requirements

**ALL implementation documentation MUST remain synchronized with the codebase**:

1. **Code Documentation**:
   - Language-appropriate documentation (JSDoc, docstrings, etc.)
   - Update inline comments when implementation changes
   - Remove outdated comments immediately

2. **Implementation Documentation**:
   - Update relevant sections in this AGENT.md file
   - Keep build and test commands current
   - Update configuration examples when defaults change
   - Document breaking changes prominently

3. **README Updates**:
   - Keep feature lists current
   - Update setup instructions when dependencies change
   - Maintain accurate command examples
   - Update version compatibility information

4. **AGENT.md Maintenance**:
   - Add new build patterns to relevant sections
   - Update "Key Learnings" with new insights
   - Keep command examples accurate and tested
   - Document new testing patterns or quality gates

### Feature Completion Checklist

Before marking ANY feature as complete, verify:

- [ ] All tests pass with appropriate framework command
- [ ] Code coverage meets 85% minimum threshold
- [ ] Coverage report reviewed for meaningful test quality
- [ ] Code formatted according to project standards
- [ ] Type checking passes (if applicable)
- [ ] All changes committed with conventional commit messages
- [ ] All commits pushed to remote repository
- [ ] .ralph/fix_plan.md task marked as complete
- [ ] Implementation documentation updated
- [ ] Inline code comments updated or added
- [ ] .ralph/AGENT.md updated (if new patterns introduced)
- [ ] Breaking changes documented
- [ ] Features tested within Ralph loop (if applicable)
- [ ] CI/CD pipeline passes

### Rationale

These standards ensure:
- **Quality**: High test coverage and pass rates prevent regressions
- **Traceability**: Git commits and .ralph/fix_plan.md provide clear history of changes
- **Maintainability**: Current documentation reduces onboarding time and prevents knowledge loss
- **Collaboration**: Pushed changes enable team visibility and code review
- **Reliability**: Consistent quality gates maintain production stability
- **Automation**: Ralph integration ensures continuous development practices

**Enforcement**: AI agents should automatically apply these standards to all feature development tasks without requiring explicit instruction for each task.
