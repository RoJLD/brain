section: Added

- The merge gate (`wi-brain-merge-gate`): `brain merge-ready PR` answers, at zero token, whether a PR may be merged:
  open and not a draft, main not moved under a file it touches since their merge base (a green CI on a stale base is
  not the merged tree), `brain merge-check` on a head that merged main, every CI check green on the head, the
  review's stamp for the head with no finding open, the public check's stamp for a repo of `public.repos`, nothing
  `brain check --public` refuses in the PR's body. Exit 0 and a stamp under `<BRAIN_HOME>/merge-ready/`, else exit 1
  and the list of what blocks. `brain merge-check`'s check takes the head to read (HEAD by default, as before). See
  docs/merge-driver.md.
