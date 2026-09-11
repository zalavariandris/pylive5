a = Analysis(
    ["launcher.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=[],
    excludes=["pytest", "numpy.tests"],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="pyflow5",
    console=False,
    debug=False,
    strip=False,
    upx=False,
)