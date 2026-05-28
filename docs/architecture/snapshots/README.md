# ACP architecture snapshots

Versioned visual references of the ACP layer architecture as it evolves
over time. Each snapshot is an HTML file that opens in a browser and shows:

- The Layer A / Layer B / Layer C architecture with agents placed in their layers
- The contract type and category taxonomies (when relevant)
- A "current state" section documenting what's built vs. designing vs. pending

## Snapshot index

| Version | Date | Trigger | File |
|---------|------|---------|------|
| v1 | 2026-05-28 | Initial snapshot before Antora Layer C content drafted | `acp_architecture_v1_2026-05-28.html` |

## When to create a new snapshot

- Workflow #2 added (DNA/cells boundary updated)
- New contract type added to the taxonomy
- New peer-pilot deployment org onboarded (Layer C changes meaningfully)
- Major architectural decision (substrate extraction, layer rename, etc.)
- Roughly quarterly even if nothing major changed, to track drift

## Naming convention

`acp_architecture_v{N}_{YYYY-MM-DD}.html`

Bump the major version (`v1` → `v2`) for changes that change the layer
structure or DNA/cells boundary. Bump conceptually as `v1.1` (still file
named `v1`) for content-only additions that don't change the architecture.
When the file's structure substantively changes, archive the prior version
in this folder and add a new entry to the index above.
