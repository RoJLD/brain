section: Added

- The push guard's private-text advice (`wi-brain-private-text-prepush`): a `git push` to a public repo that the
  guards let through gets, in the session's context, the passages of 8 words or more that the lines its commits add
  (those the remote has not) share with the owner's rules and notes on this machine, by file, line and source, never
  their text: reworded in their PR rather than before the tag, where `brain check --public --private-text` refuses
  them. Nothing is refused; the ledger records the advice as `public:private-text`, and a scan that fails lets the push
  go.
