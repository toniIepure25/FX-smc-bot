# Q.0-R Clean-Room Architecture

Q.0-R uses a newly created market-data root outside the Git repository. The root
is selected by `FX_Q0R_DATA_ROOT` or by the prescribed sibling default. Its local
absolute path is intentionally absent from committed artifacts.

The root did not exist before Q.0-R, began empty, and was created directly without
inspecting any old market-data root. Raw, canonical, checkpoint, and provider
payload files from Q.0 are not eligible for reuse.

All market I/O is mediated by an immutable capability that fixes the root,
instruments, date bounds, planned partitions, and operation type before access.
Paths are derived from the plan and are never discovered recursively.
