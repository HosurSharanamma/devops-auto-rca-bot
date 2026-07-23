"""
generate_synthetic_data.py

Generates a synthetic dataset of Jenkins CI/CD failure logs, each labelled with
a root-cause category, the underlying root cause, and a recommended fix.

This dataset plays two roles in the project:
1. Ingestion source for the RAG vector store (rag/vector_store.py).
2. Ground truth for retrieval evaluation (scripts/evaluate_retrieval.py) --
   Top-1 / Top-3 accuracy is computed by checking whether the retrieved
   incident(s) share the same root_cause_category as the query.

Run:
    python scripts/generate_synthetic_data.py
"""

import json
import os
import random

random.seed(42)

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic_jenkins_logs.json")

# Each template represents a root-cause category. Multiple concrete log
# variants are generated per category so retrieval has to work across
# paraphrases, not just exact string matches.

TEMPLATES = {
    "OOM_KILLED": {
        "root_cause": "The build container exceeded its allocated memory limit and was killed by the OS/cgroup OOM killer, typically due to a memory-heavy compile/test step or a memory leak in a long-running test suite.",
        "fix": "Increase the executor/container memory limit, split the test suite into smaller parallel shards, or add -Xmx tuning for JVM-based builds. Add memory usage monitoring to catch regressions early.",
        "variants": [
            "Build step 'mvn test' failed. Container exited with code 137. dmesg: Out of memory: Killed process (java).",
            "Jenkins agent lost connection during 'npm run build'. Container OOMKilled by Kubernetes. Memory limit was 2Gi.",
            "Gradle daemon crashed unexpectedly. Exit value 137. Kernel log shows OOM-killer invoked for gradle process.",
            "Docker build failed: the container was killed due to memory pressure while running integration tests.",
        ],
    },
    "TEST_FLAKINESS": {
        "root_cause": "A test failed intermittently due to timing/race conditions (e.g. asynchronous calls not properly awaited, shared mutable test state, or reliance on wall-clock timing) rather than an actual code defect.",
        "fix": "Add explicit waits/polling instead of fixed sleeps, isolate test state between runs, mark the test for quarantine/retry, and track flakiness rate in the test dashboard.",
        "variants": [
            "Test 'test_async_callback_completes' failed once out of five reruns with AssertionError: expected True, got False.",
            "Selenium test 'test_login_button_visible' failed with ElementNotInteractableException, passed on rerun.",
            "Integration test 'test_message_queue_consumer' timed out waiting for message, consumer received it 200ms later.",
            "Unit test 'test_cache_expiry' failed intermittently in CI but never fails locally, suspected race condition on shared cache singleton.",
        ],
    },
    "DEPENDENCY_RESOLUTION": {
        "root_cause": "The build failed to resolve one or more package dependencies due to a version conflict, a missing/removed package version, or an unreachable/misconfigured package registry.",
        "fix": "Pin dependency versions in the lockfile, verify registry connectivity/credentials, and add a private registry mirror/cache to reduce reliance on upstream availability.",
        "variants": [
            "npm install failed: 404 Not Found - GET https://registry.npmjs.org/left-pad/-/left-pad-1.3.1.tgz",
            "pip install failed: Could not find a version that satisfies the requirement torch==2.1.9 (from versions: 2.0.0, 2.0.1, 2.1.0)",
            "Maven build failed: Could not resolve dependencies for project com.acme:service-a: Could not find artifact com.acme:common:jar:3.4.1",
            "yarn install failed: Response code 401 (Unauthorized) while fetching packages from private registry.",
        ],
    },
    "CONFIG_ERROR": {
        "root_cause": "A malformed or missing configuration file (YAML/TOML/JSON) caused the pipeline to fail during the parsing/validation stage before any real build work started.",
        "fix": "Add schema validation for config files as a pre-commit hook, provide clear structured error messages on parse failure, and fail fast with actionable line/column information.",
        "variants": [
            "Pipeline failed at 'Load Config' stage: yaml.scanner.ScannerError: mapping values are not allowed here, line 12, column 12.",
            "Build aborted: tomllib.TOMLDecodeError: Invalid statement (at line 4, column 1) while parsing pyproject.toml.",
            "Jenkinsfile syntax error: expected a step @ line 34, column 5. WorkflowScript.",
            "Config validation failed: 'environment' key missing required field 'region' in deploy-config.yaml.",
        ],
    },
    "NETWORK_TIMEOUT": {
        "root_cause": "A network call to an external service (artifact repository, API dependency, or downstream microservice) exceeded the configured timeout, most likely due to transient network instability, DNS resolution delay, or the downstream service being overloaded.",
        "fix": "Add retry-with-backoff around network calls, increase timeout thresholds where appropriate, and add circuit breakers plus alerting on downstream service latency.",
        "variants": [
            "curl: (28) Failed to connect to artifacts.internal.acme.com port 443 after 30001 ms: Operation timed out.",
            "requests.exceptions.ConnectTimeout: HTTPSConnectionPool(host='api.partner.com', port=443): Max retries exceeded.",
            "Deploy step failed: kubectl apply timed out waiting for the condition after 60s, API server unreachable.",
            "Docker pull failed: net/http: TLS handshake timeout while pulling base image from private registry.",
        ],
    },
    "CREDENTIAL_AUTH_FAILURE": {
        "root_cause": "The pipeline failed because of expired, revoked, or misconfigured credentials (API keys, service account tokens, SSH keys) needed to access a required service.",
        "fix": "Rotate and store credentials in a managed secrets store (e.g. Vault, AWS Secrets Manager), add expiry alerts, and audit which pipeline stages use which credentials.",
        "variants": [
            "git push failed: fatal: Authentication failed for 'https://github.com/acme/service-a.git/'",
            "AWS CLI error: An error occurred (ExpiredToken) when calling the AssumeRole operation.",
            "Docker login failed: unauthorized: authentication required for registry.internal.acme.com",
            "SonarQube analysis failed: 401 Unauthorized - invalid or expired authentication token.",
        ],
    },
    "DISK_SPACE": {
        "root_cause": "The build agent ran out of available disk space, usually caused by accumulated build artifacts, Docker image layers, or log files that were never cleaned up between runs.",
        "fix": "Add automated workspace/artifact cleanup after each build, prune unused Docker images/volumes on a schedule, and add disk-usage alerting on build agents.",
        "variants": [
            "Build failed: java.io.IOException: No space left on device while writing target/classes.",
            "docker build failed: write /var/lib/docker/tmp/...: no space left on device",
            "Jenkins agent offline: disk usage on /var/lib/jenkins exceeded 95% threshold, marking node temporarily offline.",
            "npm ERR! ENOSPC: no space left on device, write",
        ],
    },
    "UNIT_TEST_REGRESSION": {
        "root_cause": "A genuine code regression caused unit test assertions to fail consistently across runs, indicating the most recent code change broke expected behaviour rather than any environmental/infra issue.",
        "fix": "Review the diff introduced in the failing commit, add/adjust unit tests to cover the regression, and add the failing scenario to the pre-merge check suite.",
        "variants": [
            "Test 'test_calculate_discount_applies_correctly' failed consistently across 5/5 runs: AssertionError: expected 90.0, got 100.0",
            "Test suite 'PaymentServiceTests' failed 12 tests after merging PR #482, all related to currency rounding logic.",
            "Contract test 'test_order_api_response_schema' failed: response missing required field 'orderStatus'.",
            "Regression test 'test_user_permission_boundary' failed on every run since commit a3f9c1.",
        ],
    },
    "INFRA_PROVISIONING_FAILURE": {
        "root_cause": "The pipeline failed while provisioning or scaling infrastructure (Kubernetes pods, cloud VMs, Terraform-managed resources), typically due to quota limits, misconfigured IAM permissions, or a broken infrastructure-as-code definition.",
        "fix": "Add quota monitoring and pre-flight checks before provisioning, validate Terraform plans in CI before apply, and ensure least-privilege IAM roles are correctly scoped and tested.",
        "variants": [
            "Terraform apply failed: Error: Error creating VPC: VpcLimitExceeded: The maximum number of VPCs has been reached.",
            "kubectl apply failed: pods 'worker-deploy' is forbidden: exceeded quota: compute-resources, requested: cpu=4, used: cpu=30, limited: cpu=32",
            "Provisioning step failed: AccessDenied: User is not authorized to perform: ec2:RunInstances",
            "Helm install failed: 1 error occurred: timed out waiting for the condition, deployment 'api-gateway' not ready.",
        ],
    },
    "LINTING_STATIC_ANALYSIS": {
        "root_cause": "The pipeline failed at a static analysis/linting gate because newly introduced code violated formatting, style, or security-scanning rules enforced by the project's quality gate.",
        "fix": "Run linters/formatters locally via pre-commit hooks before pushing, and provide clear autofix suggestions in CI logs to shorten the feedback loop.",
        "variants": [
            "ESLint failed: 14 errors found, 3 of which are auto-fixable with the `--fix` option.",
            "flake8 failed: E501 line too long (92 > 79 characters) in utils/log_cleaning.py:44",
            "Bandit security scan failed: B105 hardcoded_password_string detected in config/settings.py",
            "clippy failed: warning: unused variable 'cfg' denied by #[deny(warnings)] in src/main.rs",
        ],
    },
}


def build_dataset():
    records = []
    idx = 1
    for category, spec in TEMPLATES.items():
        for variant in spec["variants"]:
            records.append(
                {
                    "id": f"inc-{idx:04d}",
                    "log_text": variant,
                    "root_cause_category": category,
                    "root_cause": spec["root_cause"],
                    "fix_recommendation": spec["fix"],
                }
            )
            idx += 1
    random.shuffle(records)
    return records


def main():
    records = build_dataset()
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    print(f"Wrote {len(records)} synthetic incidents to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
