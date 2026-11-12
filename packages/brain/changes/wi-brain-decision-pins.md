section: Added

- Decision pins (`wi-brain-decision-pins`, `docs/pins.md`): `brain adr pin ID --touches PATH|CODEREF --holds LINE`
  pins an ADR, an SDR or an answered DDR to the code it governs, in `pins.yaml` beside the decision log (a `holds`
  line is never edited: an override is a new ADR). `brain impact --diff` lists the pinned decisions a change touches
  (`pins` in `--json`); `brain review check HEAD --pr N` (or `--body FILE`) and `brain merge-ready` (its new `pins`
  check) refuse until the PR body says `Keeps ID` or `Overrides ID: why`, an override with its REVERSAL ADR; `brain
  check` warns on a pin of an unknown, pending or superseded decision, a malformed row and a decision pinned twice.
