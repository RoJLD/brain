section: Upgrade

**Every machine and the brain's CI on this engine before an SR with the new fields is committed.** An SR the Stop hook
writes now holds `provider`, `harness`, `account` and `plan`: an older engine reads them with a note, keeps them when
it rewrites the record, and refuses them in strict mode (CI, `BRAIN_STRICT=1`). Pin the brain's CI to this release and
update each machine (`brain update`) first; until then, review the session records on a machine that runs it.
