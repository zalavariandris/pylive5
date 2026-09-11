# PyFlow5
live dataflow graph coding, by connecting python functions

## setup for dev
create the venv:
`uv venv`
`uv sync`
install submodules: `uv pip install -e ./PyFlow5`

## dev docs
docs/

## Build Exe

```powershell
uv sync --extra exe
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm pyflow5-bundle.spec
```