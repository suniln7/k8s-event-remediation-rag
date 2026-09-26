# Playbook: CrashLoopBackOff

## Symptom
Container starts, then exits, repeatedly, with Kubernetes backing off the restart interval
exponentially (10s, 20s, 40s ... capped at 5m). Event reason `BackOff`, message like
`Back-off restarting failed container`. `restartCount` climbs steadily.

## Common root causes
1. **Application crashes on startup** -- bad config, missing required env var, unreachable
   dependency (DB/broker not ready yet), unhandled exception in init code.
2. **Wrong command/entrypoint** -- image's default CMD doesn't match what the workload expects,
   or an overridden `command:`/`args:` is invalid for this image.
3. **Failing readiness/liveness probe causing repeated kills** -- distinct from a genuine app
   crash; the process itself may be fine but the probe is misconfigured (see
   `probe-failures.md`).
4. **OOMKilled loop** -- container is being killed for memory, then restarting, then getting
   killed again (see `oomkilled.md` -- `describe_pod` will show `reason=OOMKilled` on the
   *previous* terminated state, not `Error`).
5. **Missing ConfigMap/Secret volume or key** the app reads at startup and fails fast without.

## Diagnostic steps
- `describe_pod` first: check the **previous terminated state's** `reason` and `exit_code`.
  - `exit_code=1` (or another app-specific non-zero code): look at logs.
  - `reason=OOMKilled`: this is a memory problem, not a code bug -- go to `oomkilled.md`.
  - `exit_code=0` and it still restarts: probe or supervisor issue, not a crash.
- `get_pod_logs` with `previous=True`: the *current* container is usually too new to have
  useful logs (it just restarted); the crash's real stack trace/error is in the previous
  instance's log tail.
- Check the container's `command`/`args` and required env vars/mounted ConfigMaps/Secrets
  against what the log shows it looking for.

## Remediation patterns
- **Missing env var / config**: add it to the pod spec.
  ```yaml
  env:
    - name: REQUIRED_SETTING
      value: "correct-value"
  ```
- **Dependency not ready yet**: add an init container or startup retry/backoff in the app,
  rather than assuming the dependency is always up before this pod starts.
- **Wrong command**: fix `command:`/`args:` to match what the image actually expects.
- **Probe misconfigured**: see `probe-failures.md` -- don't treat this as an app bug.
