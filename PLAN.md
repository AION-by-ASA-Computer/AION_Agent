# Implementation Plan - Fix Environment Resolution and Cache Clearing in Filesystem Policy Update

## Problem Description
In `src/api/settings_api.py`, the `update_fs_policy` endpoint writes policy updates and env changes using the centralized helper `_write_env()`. However, the updated variables are not loaded into the active process's `os.environ` unless the process restarts. 

Furthermore, a commented block of code in `update_fs_policy` (lines 317-323) was attempt to load the environment using manual path resolution logic. This logic has several critical bugs:
1. `_ROOT` is undefined in the module.
2. `load_dotenv` is not imported.
3. The resolved environment path is resolved inconsistently compared to the helper function `_get_env_path()`.
4. The cached `load_fs_policy` is never cleared, meaning the policy remains stale in local dev even if `os.environ` is updated.

## Proposed Changes

### Backend Component

#### [MODIFY] [settings_api.py](file:///Users/LucaDago/Desktop/agent.nosync/AION_Agent/src/api/settings_api.py)
- Import `load_dotenv` from `dotenv` at the top of the file.
- Import `load_fs_policy` from `src.runtime.agent_fs_policy` to allow cache clearing.
- Clean up the commented/broken code block in `update_fs_policy`.
- Replace it with a clean env reload and cache clear:
  ```python
  env_path = _get_env_path()
  if env_path.is_file():
      from dotenv import load_dotenv
      load_dotenv(env_path, override=True)
  
  # Clear the policy cache so changes take effect immediately
  from src.runtime.agent_fs_policy import load_fs_policy
  load_fs_policy.cache_clear()
  ```
- Similarly, in `update_settings`, reload the env variables to ensure they are available in `os.environ` for the rest of the current session:
  ```python
  env_path = _get_env_path()
  if env_path.is_file():
      from dotenv import load_dotenv
      load_dotenv(env_path, override=True)
  ```

