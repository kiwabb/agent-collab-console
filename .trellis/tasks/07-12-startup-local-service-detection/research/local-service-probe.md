# Local service probe research

## Existing behavior

* `ProjectRunManager.status()` only reads its in-memory process map, so external terminal/IDE processes and state lost across backend restart are invisible.
* `Project` persists `setup_script` and `run_command`, but not `access_url`.
* The latest successful Operations Engineer task keeps the analyzed `access_url` in `CodexTask.result` JSON; the frontend already reads that result.
* Startup Config currently equates `runStatus.running` with a console-owned process and only polls while that flag is true.

## Chosen contract

* The backend resolves the newest successful `project_script_suggestion` task for the project and accepts its URL only when the suggestion's `run_command` matches the project's current command. A missing, malformed, or mismatched newest result does not fall back to an older URL.
* `running` keeps meaning “the console owns a live process”. A nested `service` result independently reports `reachable`, `unreachable`, `not_configured`, or `invalid_url`.
* Only `running=true` grants Stop ownership. `running=false` plus `service.state=reachable` means an address is serving outside console ownership.
* Start performs the same reachability check immediately before environment materialization/process creation and refuses with `service_already_reachable` when an external listener responds.

## Probe security and semantics

* Parse with `urlsplit`; allow only HTTP(S), no userinfo, and exact loopback hosts (`localhost`, loopback IPs, plus wildcard bind addresses normalized to connectable loopback IPs).
* Reject public, private-LAN, link-local, metadata, and hostname-lookalike targets before constructing the HTTP client request.
* Rebuild a canonical URL from validated parts; do not request the original string after validation.
* Use `trust_env=False` and `follow_redirects=False`.
* Stream GET response headers without reading the body. Any HTTP response, including 3xx/4xx/5xx, proves an HTTP listener is reachable.
* Catch only `httpx.TimeoutException` and `httpx.RequestError` as expected unreachable results. Unexpected failures propagate so stale frontend state is preserved rather than replaced with a false offline result.

## Testing boundaries

* Unit-test URL validation for localhost, IPv4/IPv6 loopback, wildcard normalization, userinfo, schemes, invalid ports, private/public/link-local hosts, and lookalike domains.
* Use `httpx.MockTransport` to prove redirects are not followed, response bodies are not consumed, all status codes count as reachable, and request/timeout errors become unreachable.
* API tests cover the status matrix and the duplicate-start refusal.
* Frontend pure-state tests cover managed-ready, managed-starting, externally reachable, offline, and unknown states; source/API tests cover polling and typed refusal handling.
