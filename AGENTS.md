# Repository instructions

## Python environment

- Use `F:\unimel\sortax\.venv\Scripts\python.exe` for this repository's Python commands.
- Run `python.exe -m pytest` and `python.exe -m mypy` with the required elevated sandbox
  permission on the first attempt; the user has authorized these two narrow validation workflows.
- The virtual environment and its Python 3.12.3 base installation are valid. If a sandboxed
  command reports `Unable to create process` for the base interpreter under
  `C:\Users\12395\AppData\Local\Programs\Python\Python312`, treat that as a sandbox execution
  restriction and rerun the same command with the required elevated permission.
- Do not download a temporary Python runtime, install another Python distribution, or rebuild
  `.venv` for that error. Only consider repairing the environment if the same interpreter command
  also fails outside the sandbox, and obtain the user's approval before replacing it.
- Keep persistent approvals narrow. Prefer separate command prefixes for
  `.venv\Scripts\python.exe -m pytest` and `.venv\Scripts\python.exe -m mypy`; never request a
  blanket approval for arbitrary Python execution.
