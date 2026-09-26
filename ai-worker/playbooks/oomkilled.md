# Playbook: OOMKilled

## Symptom
Container's *previous* terminated state shows `reason=OOMKilled`, `exit_code=137` (128 + SIGKILL's
9). Often presents to the user as a CrashLoopBackOff, but the actual proximate cause is memory,
not an application bug.

## Common root causes
1. **`resources.limits.memory` set too low** for the workload's real usage (most common in a
   learning/dev cluster where limits are guessed rather than measured).
2. **Genuine memory leak** in the application -- usage climbs over time until it hits the limit,
   rather than being high immediately at startup.
3. **No limit set at all**, but the *node* is under memory pressure and the kubelet evicts/OOM
   kills lower-priority pods first (`describe_pod`'s conditions may show `MemoryPressure`).
4. **Traffic/batch-size spike** pushes a normally-fine limit over the edge momentarily.

## Diagnostic steps
- `describe_pod`: confirm `state=Terminated(reason=OOMKilled, exit_code=137)` on the
  container status, and read the configured `resources.limits`/`requests` for that container.
- `list_recent_warning_events` in the namespace: repeated OOMKilled across multiple pods at the
  same time points at node-wide memory pressure, not a single workload's limit being too tight.
- If logs exist right up to the kill with no error, that's consistent with OOM (SIGKILL gives
  the process no chance to log a clean error) rather than an application-level crash.

## Remediation patterns
- **Limit too low for normal usage**: raise `resources.limits.memory` (and usually `requests`
  too, so the scheduler places it on a node that can actually sustain that usage).
  ```yaml
  resources:
    requests:
      memory: "256Mi"
    limits:
      memory: "512Mi"  # was 128Mi -- too low for steady-state usage seen in logs/metrics
  ```
- **Suspected leak**: don't just raise the limit indefinitely -- that delays the crash, it
  doesn't fix it. Flag for profiling/investigation in the app itself; a higher limit is a
  short-term mitigation, not the remediation.
- **Node-wide pressure**: this is a capacity problem, not a single manifest's problem -- either
  add node capacity or reduce total scheduled memory requests in the cluster.
