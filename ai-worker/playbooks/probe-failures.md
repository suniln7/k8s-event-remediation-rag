# Playbook: Liveness / Readiness Probe Failures

## Symptom
Event reason `Unhealthy`, message like `Liveness probe failed: ...` or
`Readiness probe failed: ...`. A **readiness** failure keeps the pod running but pulls it out
of Service endpoints (traffic stops routing to it). A **liveness** failure gets the container
*killed and restarted* -- repeated liveness failures look identical to CrashLoopBackOff from
the outside, but the root cause is the probe, not the app crashing on its own.

## Common root causes
1. **Probe path/port wrong** -- e.g. probing `/healthz` on a port the app doesn't serve health
   checks on, or a path that 404s.
2. **`initialDelaySeconds` too short** for a slow-starting app -- the app is still initializing
   (loading data, warming caches, connecting to a DB) when the first probe fires, gets marked
   unhealthy, and is killed before it ever had a chance to become ready.
3. **`timeoutSeconds` too aggressive** for an endpoint that's occasionally slow under load --
   probe times out even though the app would have answered a moment later.
4. **App genuinely unhealthy**: the probe is correctly configured and correctly reporting a
   real problem (e.g. lost its DB connection) -- don't assume every probe failure is a
   configuration bug.

## Diagnostic steps
- `describe_pod`: read the exact probe failure message (often includes the HTTP status code or
  connection error returned from the probe path).
- Compare `initialDelaySeconds`/`periodSeconds`/`timeoutSeconds` against how long the app
  actually takes to become ready (check logs for a "ready"/"started" log line timestamp vs. pod
  start time).
- `get_pod_logs`: if the app logs show it was still initializing when the kill happened, that's
  a timing problem, not an app bug. If the app logs a genuine internal error right before the
  probe started failing, the probe is doing its job correctly.

## Remediation patterns
- **Startup too slow for current probe timing**: increase `initialDelaySeconds`, or better,
  add a `startupProbe` so liveness doesn't even begin checking until startup is confirmed done.
  ```yaml
  startupProbe:
    httpGet:
      path: /healthz
      port: 8080
    failureThreshold: 30
    periodSeconds: 2
  livenessProbe:
    httpGet:
      path: /healthz
      port: 8080
    periodSeconds: 10
  ```
- **Wrong path/port**: correct it to match what the app actually serves.
- **Timeout too tight**: raise `timeoutSeconds` modestly rather than removing the probe.
