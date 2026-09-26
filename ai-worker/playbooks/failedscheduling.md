# Playbook: FailedScheduling

## Symptom
Pod stays `Pending` indefinitely. Event reason `FailedScheduling`, message typically starts
with `0/N nodes are available:` followed by a list of reasons per node.

## Common root causes (read the exact per-node reason text -- it's usually explicit)
1. **Insufficient resources**: `Insufficient cpu` / `Insufficient memory` -- the requested
   `resources.requests` don't fit on any current node's allocatable capacity.
2. **Node selector / affinity mismatch**: `didn't match Node selector` / `didn't match pod
   affinity/anti-affinity rules` -- the pod asks for a label no node has, or an anti-affinity
   rule excludes every available node.
3. **Taints without matching tolerations**: `node(s) had untolerated taint {key: value}` --
   very common right after standing up a fresh kind cluster if the control-plane taint wasn't
   accounted for, or a custom taint was added for a node pool.
4. **PersistentVolumeClaim not bound / no matching StorageClass** -- pod can't schedule until
   its volume claim is satisfied.
5. **Too few nodes for the requested topology spread / anti-affinity** -- e.g. `maxSkew` rules
   that can't be satisfied with only 1-2 worker nodes (common in a 1-2 node kind cluster).

## Diagnostic steps
- `describe_pod`: the `FailedScheduling` event message enumerates *why each node* was rejected
  -- read it literally, it names the exact constraint that failed.
- `list_recent_warning_events`: if many pods are `Pending` with the same reason, it's a
  cluster-capacity or taint issue, not something specific to one workload.
- Cross-check the pod's `resources.requests`, `nodeSelector`/`affinity`, and `tolerations`
  against the actual node labels/taints/capacity.

## Remediation patterns
- **Resource requests too high for a small dev cluster**: lower `requests` to something the
  cluster can actually satisfy.
  ```yaml
  resources:
    requests:
      cpu: "100m"      # was "2" -- no single node in this kind cluster has 2 full cores free
      memory: "128Mi"
  ```
- **Missing toleration for an existing taint**:
  ```yaml
  tolerations:
    - key: "node-role.kubernetes.io/control-plane"
      operator: "Exists"
      effect: "NoSchedule"
  ```
- **Node selector referencing a label no node has**: fix the selector to match real node
  labels, or label the intended node.
