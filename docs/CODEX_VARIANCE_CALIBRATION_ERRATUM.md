# Calibration v1 Snapshot Guidance Erratum

The zero-call calibration preflight stopped because the experiment validator rejected every `AGENTS.md`. The pinned source commit `db187e0f48f54222dd250502a2e40b7f1fb16401` legitimately tracks root `AGENTS.md` as blob `0c8baf10e4f781c6b9eaa03c38a24b40d4e1978c`. The frozen plan's "No benchmark AGENTS.md" rule prohibits added experiment-specific instructions; it does not require deleting committed source guidance.

Snapshot validation now permits guidance only when its path, type, and bytes match Git's committed tree and blob. Unexpected, ignored, modified, or deleted guidance fails preflight. Both arms retain the same pinned instructions. Production isolation remains unchanged: Apps and plugins disabled, user config ignored, strict config, read-only sandbox, and no MCP registration. The v1 plan, historical outcome, task, source, and ABBA order remain unchanged. This erratum does not authorize or report any calibration model call.
