# Output Contract

Every final-producing mode writes one validated SRT/TXT pair. Final files live directly in the selected output directory; downloads, raw ASR, normalized sources, prompts, metadata, seam data, QC, and other evidence live under `_subtitle_work/` with content-addressed, component-safe names.

Publication rules:

- Parse and validate inputs before creating final artifacts.
- Stage short same-directory temporary files and byte-check SRT/TXT against one serialization.
- Use one normalized-identity, single-link regular-file lock for the pair.
- Refuse existing outputs by default. `--replace-existing` is the only replacement authorization.
- When replacement is authorized, archive existing members and restore them if promotion fails. Report incomplete rollback with archive evidence.
- Reject input/output aliases, directories, symlinks, reparse points, hardlinked locks, and non-regular targets.
- Promote TXT first and SRT last; SRT is the completion marker.

Standalone QC writes its full report atomically. Default report names are digest-suffixed and cannot alias inputs. Console JSON is ASCII-safe and bounded so legacy Windows code pages and large reports do not change the exit contract.

With `--require-language`, metadata records the required and detected language, evidence origin/confidence, exact source path, and SHA-256 of canonical emitted SRT bytes. Its content-addressed filename also binds the complete metadata payload, including any immutable context path and context SHA-256, so a different video cannot overwrite earlier evidence. Downstream consumers must validate those exact bindings.
