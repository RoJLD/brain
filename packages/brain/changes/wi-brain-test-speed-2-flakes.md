section: Fixes

- **Three tests that failed under load are fixed, not retried** (`wi-brain-test-speed-2`).
  `test_sessions::test_a_masters_earlier_transcript_raises_no_alert`: the test rewrote the app's file with a cli id of
  the same length, and on NTFS the second write could land in the same mtime tick, so `sessions.app_index`'s cache
  (by size and mtime) kept the earlier metadata; the tests' `app` fixture gives each rewrite a newer mtime.
  `test_memory::test_hook_scripts_end_to_end`: the fake gh holds the detached job at a gate the test opens once the
  hook has returned, instead of a 10 s bound a loaded machine overran. The docker-marked
  `test_docker_compose_config_accepts_the_rendering` waits 120 s for a cold docker client, not a check's 15 s.
  Fewer git processes per run: `test_release_check`'s tagged repo is made once per worker and copied, and
  `make_repo.commit` reads the new sha from the branch's ref file (`conftest.head_sha`).
