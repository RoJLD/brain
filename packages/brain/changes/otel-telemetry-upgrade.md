section: Upgrade

**Restart the sovereign collector on its new configuration** (where the sovereign stack runs): `brain bundle apply
sovereign`, then `brain down otel-collector` and `brain up otel-collector`; `brain telemetry status` says it receives
again.
