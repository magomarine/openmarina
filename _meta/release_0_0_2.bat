@echo off
setlocal
REM openmarina 0.0.2 release - v2.
REM v1 bug (2026-08-12): pushd "%~dp0" landed in _meta\, so the lock cleanup
REM looked for _meta\.git\ and the gate resolved to _meta\_meta\release_qc.py.
REM The repo guard passed because rev-parse --show-toplevel is cwd-independent.
REM v2 goes to the repo ROOT and asserts we are actually at the root.
REM ASCII only + CRLF on purpose (a .bat with non-ASCII breaks under the OEM codepage).

cd /d "%~dp0.." || (echo [STOP] cannot cd to repo root & goto :end)

for /f "delims=" %%R in ('git rev-parse --show-toplevel 2^>nul') do set "TOP=%%R"
echo Repo toplevel: %TOP%
echo Working dir  : %CD%
echo %TOP% | findstr /I /C:"openmarina" >nul
if errorlevel 1 (echo [STOP] not the openmarina repo. Nothing done. & goto :end)
git remote get-url origin | findstr /I /C:"magomarine/openmarina" >nul
if errorlevel 1 (echo [STOP] origin is not magomarine/openmarina. & goto :end)
REM must be AT the root, not in a subdirectory - this is the v1 bug, guarded
for /f "delims=" %%P in ('git rev-parse --show-prefix 2^>nul') do set "PREFIX=%%P"
if not "%PREFIX%"=="" (echo [STOP] not at repo root, prefix=%PREFIX% & goto :end)
if not exist "pyproject.toml" (echo [STOP] pyproject.toml not here & goto :end)

echo.
echo [1/7] clear stale locks left by the sandbox
if exist ".git\index.lock" del /q ".git\index.lock"
if exist ".git\HEAD.lock" del /q ".git\HEAD.lock"
if exist ".git\objects\maintenance.lock" del /q ".git\objects\maintenance.lock"
for /d %%D in (".git\objects\??") do if exist "%%D\tmp_obj_*" del /q "%%D\tmp_obj_*"
if exist ".write_probe" del /q ".write_probe"
if exist ".git\index.lock" (echo [STOP] index.lock still present - close other git tools & goto :end)

echo [2/7] point HEAD and index at origin/main, leave the working tree alone
git fetch origin main
git reset --mixed 958e65a
if errorlevel 1 (echo [STOP] reset failed & goto :end)
git add -A
if errorlevel 1 (echo [STOP] git add failed & goto :end)
git status --short

echo.
echo [3/7] release gate - nothing ships if this fails
python _meta\release_qc.py
if errorlevel 1 (echo [STOP] release_qc FAILED. Not committing. & goto :end)

echo [4/7] commit
git commit -F "_meta\RELEASE_MSG_0_0_2.txt"
if errorlevel 1 (echo [STOP] commit failed & goto :end)

echo [5/7] tags
git tag -a v0.0.1 a3bbcf2 -m "openmarina 0.0.1 (published to PyPI 2026-06-24)"
git tag -a v0.0.2 -m "openmarina 0.0.2 - summary() + SignalK output"

echo [6/7] push
git push origin main --follow-tags

echo [7/7] build and publish 0.0.2 only
python -m pip install --upgrade build twine
if exist "dist" rmdir /s /q dist
python -m build
if errorlevel 1 (echo [STOP] build failed & goto :end)
python _meta\release_qc.py --dist
if errorlevel 1 (echo [STOP] dist gate FAILED. Not uploading. & goto :end)
python -m twine upload dist\openmarina-0.0.2*

echo.
git log --oneline -3
git tag

:end
echo.
pause
