# CI Debugging Guide for Agents

This guide helps agents (and humans) debug CI/CD pipeline failures effectively.

## Quick Start: Finding Failure Details

### 1. Get Recent Runs
```bash
# List recent workflow runs
gh run list --limit 10

# Filter by workflow name
gh run list --workflow pytest.yaml --limit 5

# See all runs (including those from PRs)
gh run list --all --limit 20
```

### 2. Identify Failing Jobs
```bash
# View a specific run
gh run view <RUN_ID>

# Show only failed jobs
gh run view <RUN_ID> --json conclusion,jobs -q '.jobs[] | select(.conclusion == "failure") | {name, html_url}'
```

### 3. Access Logs
```bash
# Get full logs for a run
gh run view <RUN_ID> --log

# Get only failed step logs (most efficient)
gh run view <RUN_ID> --log-failed

# Save logs to a file for analysis
gh run view <RUN_ID> --log > ci_logs.txt
```

## Common Failure Patterns

### Pattern 1: Container Startup Failures

**Symptoms:**
- Services fail to start
- Connection refused errors
- Timeouts waiting for services

**Where to look:**
```bash
# Check "Start containers" or "Initialize containers" stages
gh run view <RUN_ID> --log | grep -A 20 "Starting.*service"

# Check if containers are healthy
gh run view <RUN_ID> --log | grep -E "(healthy|started|ready|listening)"

# Look for Docker errors
gh run view <RUN_ID> --log | grep -i "error\|exception\|failed\|exit"
```

**Key sections:**
- `Pull docker` stage - image pull failures
- `Initialize containers` stage - container creation issues
- `Start <service>` stages - individual service startup
- `Stop containers` stage - often contains diagnostic info about why containers stopped

### Pattern 2: Test Failures (4xx/5xx Errors)

**Symptoms:**
- HTTP 404, 500, 422 errors
- Connection refused
- Timeout errors

**Where to look:**
```bash
# Find the actual error messages
gh run view <RUN_ID> --log-failed | grep -E "(Error|error|FAIL|Fail|AssertionError|HTTPStatusError)"

# Get the full test output
gh run view <RUN_ID> --log | grep -A 50 "FAILED\|Error\|assert"

# Check actual HTTP requests made
gh run view <RUN_ID> --log | grep -E "(HTTP Request:|GET|POST|PUT|DELETE).*(" | head -50
```

**Example from this repo:**
```
HTTP Request: GET http://localhost:8000/api/catalogmatch/api/catalogmatch/catalogs/ "HTTP/1.1 404 Not Found"
```
Notice the **double path prefix** `/api/catalogmatch/api/catalogmatch/` - this indicates a URL construction issue.

### Pattern 3: Dependency Installation Failures

**Symptoms:**
- Package not found
- Version conflicts
- Installation timeouts

**Where to look:**
```bash
# Check package installation steps
gh run view <RUN_ID> --log | grep -A 30 "pip install\|poetry install\|npm install"

# Look for resolution errors
gh run view <RUN_ID> --log | grep -i "could not\|not found\|conflict\|incompatible"
```

### Pattern 4: Environment Variable Issues

**Symptoms:**
- Missing configuration
- Wrong connection strings
- Authentication failures

**Where to look:**
```bash
# Check environment variable setup
gh run view <RUN_ID> --log | grep -E "(export|set|env:|environment:)" | head -20

# Verify what env vars were actually used
gh run view <RUN_ID> --log | grep -A 5 "Running with"
```

## Advanced Techniques

### Compare Working vs Broken Runs
```bash
# Get logs from a successful run
gh run view <SUCCESS_RUN_ID> --log > success.log

# Get logs from a failing run
gh run view <FAIL_RUN_ID> --log > fail.log

# Diff them
diff -u success.log fail.log | head -100
```

### Search Across Multiple Runs
```bash
# Find all recent failures with a specific error
gh run list --all --limit 50 | awk '/failure/ {print $1}' | while read run_id; do
  echo "=== Run $run_id ==="
  gh run view $run_id --log-failed | grep "SpecificErrorMessage" || echo "Not found"
done
```

### Check Cleanup Stages

Even when the main job fails, cleanup stages often contain valuable diagnostic information:

```bash
# Look at "Stop containers", "Teardown", or "Post" stages
gh run view <RUN_ID> --log | grep -A 30 "Stop containers\|Stopping\|Cleanup"
```

**What to look for:**
- Container exit codes
- Last logged messages before shutdown
- Resource constraints (OOM kills, etc.)

### Real-Time Monitoring (During Development)

If you have push permissions and want to iterate quickly:

```bash
# Watch CI progress in real-time
gh run watch <RUN_ID>

# Stream logs as they come in
gh run view <RUN_ID> --log --watch
```

## Repo-Specific Notes

### catalog-server Integration Tests

**Common issues:**

1. **URL Construction Problems**
   - Check if `CATALOGSERVER_URI` env var is set correctly
   - Verify `ROOT_PATH` is exported before starting uvicorn
   - Look for double path prefixes in HTTP requests

2. **MongoDB Connection Issues**
   - Verify MongoDB container started successfully
   - Check `MONGO_URI` connectivity
   - Look for authentication errors

3. **Service Dependencies**
   ```bash
   # Check if all services started
gh run view <RUN_ID> --log | grep -E "(mongo|uvicorn|server)" | grep -E "(started|running|ready|listening)"
   ```

**Critical log sections:**
- `Start uvicorn server` - verifies web server is listening
- `Populate test catalog` - confirms MongoDB has test data
- `Test with pytest` - contains actual test failures

## Best Practices

### 1. Always Check the Latest Run First
```bash
# Get the most recent run for the current branch
gh run list --head --limit 1
```

### 2. Isolate the First Failure
Many pipelines have multiple dependent jobs. Find the FIRST job that failed:
```bash
# List jobs in order
gh api repos/<OWNER>/<REPO>/actions/runs/<RUN_ID>/jobs --jq '.jobs[] | {name, conclusion, started_at}'
```

### 3. Don't Guess - Use Evidence
Always quote actual log excerpts when diagnosing issues. Never say "probably" without showing the proof from logs.

### 4. Check Both Setup and Teardown
Failure causes are often revealed in:
- Job setup phases (missing dependencies)
- Service initialization (container failures)
- Cleanup/teardown phases (resource exhaustion, crashes)

### 5. Understand the Workflow Structure
Before debugging, familiarize yourself with:
- Which services are defined
- What environment variables are set
- How containers communicate
- Where persistent data lives

## Example: Debugging Our Recent Issue

**Problem:** Integration tests failing with 404 errors

**Debug process:**

1. Get the failing run:
   ```bash
   gh run list --workflow pytest.yaml --limit 5
   # Found: 42477106791
   ```

2. Check failed jobs:
   ```bash
   gh run view 42477106791 --log-failed
   ```

3. Found the smoking gun:
   ```
   HTTP Request: GET http://localhost:8000/api/catalogmatch/api/catalogmatch/catalogs/ "HTTP/1.1 404 Not Found"
   ```

4. Diagnosed the issue:
   - Double `/api/catalogmatch` prefix
   - Caused by incorrect URL construction in conftest.py
   - Confirmed missing ROOT_PATH env var for uvicorn

5. Fixed both issues and verified

## Tools Reference

### GitHub CLI Commands

| Command | Purpose |
|---------|---------|
| `gh run list` | List workflow runs |
| `gh run view <ID>` | View run details |
| `gh run view <ID> --log` | View full logs |
| `gh run view <ID> --log-failed` | View only failed steps |
| `gh run watch <ID>` | Monitor run in real-time |
| `gh api <endpoint>` | Raw API access for complex queries |

### Useful Grep Patterns

```bash
# HTTP errors
grep -E "HTTP/[0-9.]+" \"[45][0-9]{2}"

# Exception tracebacks
grep -A 20 "Traceback"

# Assertion failures
grep -B 5 -A 10 "AssertionError"

# Connection errors
grep -i "connection\|refused\|timeout\|timed out"

# Process exits
grep -E "(exited|killed|terminated|signal)"

# Container issues
grep -i "docker\|container\|image\|pull\|network"
```

## Final Advice

When in doubt:
1. Start with `--log-failed` to see only relevant parts
2. Look for the FIRST error in chronological order
3. Check both the failing step AND the setup steps before it
4. Quote actual log lines in your diagnosis
5. Remember that cleanup stages often have clues about what went wrong
