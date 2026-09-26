# Playbook: ErrImagePull / ImagePullBackOff

## Symptom
Pod stuck in `Waiting` state. Event reasons seen: `Failed` with message `Error: ErrImagePull`,
followed by repeated `Error: ImagePullBackOff`. Container never starts; `restartCount` stays 0
because the container has never successfully run once.

## Common root causes
1. **Bad tag or repository name** -- typo in `image:`, or the tag was never published
   (e.g. `nginx:this-tag-does-not-exist`). Kubelet log shows
   `failed to resolve reference "docker.io/library/<image>:<tag>"`.
2. **Image is genuinely private** and the pod has no matching `imagePullSecrets`, or the
   secret exists but is in the wrong namespace (pull secrets are namespace-scoped).
3. **Registry auth expired** -- a previously-working `imagePullSecrets` credential rotated out.
4. **Network/proxy/DNS problem on the node** reaching the registry -- manifests as `EOF`,
   `TLS handshake timeout`, or `i/o timeout` in the message rather than a clean 404/manifest
   error. This points at node-level networking, not the image reference itself.
5. **Registry-side rate limiting** (e.g. Docker Hub anonymous pull limits) -- message usually
   says `toomanyrequests` explicitly.

## Diagnostic steps
- `describe_pod`: confirms the container is `Waiting` with `reason=ErrImagePull` or
  `ImagePullBackOff`, and shows the exact `image:` string being requested.
- `list_recent_warning_events`: if *multiple, unrelated* pods on the same node are all failing
  image pulls around the same time, suspect node-level network/registry connectivity rather
  than a per-pod typo.
- Compare the failing image string against what's actually published (registry tag list) --
  a typo'd tag/repo is by far the most common cause in a dev/learning cluster.

## Remediation patterns
- **Typo'd tag/repo**: correct the `image:` field.
  ```yaml
  spec:
    containers:
      - name: app
        image: nginx:1.27  # was: nginx:this-tag-does-not-exist
  ```
- **Private image, missing pull secret**: add `imagePullSecrets` to the pod spec (or its
  ServiceAccount) referencing a `kubernetes.io/dockerconfigjson` Secret in the *same namespace*.
  ```yaml
  spec:
    imagePullSecrets:
      - name: regcred
  ```
- **Network/proxy issue**: not fixable from inside the manifest -- escalate as an
  infrastructure/node problem (proxy config, DNS, MTU/firewall), not a workload bug.
