"""Local multi-version test and release automation."""

from pathlib import Path

import nox

SUPPORTED_PYTHONS = ("3.11", "3.12", "3.13", "3.14")
DEFAULT_PYTHON = "3.14"

nox.needs_version = ">=2026.4.10"
nox.options.default_venv_backend = "uv"


def _sync(session: nox.Session, *, install_project: bool = True) -> None:
    """Sync locked dependencies into the session environment."""
    args = ["sync", "--locked", "--active"]
    if not install_project:
        args.append("--no-install-project")
    session.run_install("uv", *args, external=True)


@nox.session(python=DEFAULT_PYTHON, tags=["quality"], download_python="always")
def lint(session: nox.Session) -> None:
    """Run Ruff lint and formatting checks."""
    _sync(session)
    session.run("ruff", "check", ".")
    session.run("ruff", "format", "--check", ".")


@nox.session(python=DEFAULT_PYTHON, tags=["quality"], download_python="always")
def typecheck(session: nox.Session) -> None:
    """Run basedpyright type checks."""
    _sync(session)
    session.run("basedpyright")


@nox.session(python=DEFAULT_PYTHON, tags=["quality"], download_python="always")
def dependencies(session: nox.Session) -> None:
    """Run source security and dependency-declaration checks."""
    _sync(session)
    session.run("bandit", "-q", "-c", "pyproject.toml", "-r", "src", "examples")
    session.run("deptry", "src", "examples")


@nox.session(python=SUPPORTED_PYTHONS, tags=["tests"], download_python="always")
def tests(session: nox.Session) -> None:
    """Run tests on every supported Python version."""
    _sync(session)
    session.run("python", "-m", "pytest", *(session.posargs or ["-q"]))


@nox.session(python=SUPPORTED_PYTHONS[0], tags=["tests"], download_python="always")
def minimum_dependencies(session: nox.Session) -> None:
    """Run tests with minimum direct dependency versions."""
    session.run(
        "uv",
        "run",
        "--isolated",
        "--resolution",
        "lowest-direct",
        "--no-default-groups",
        "--group",
        "test",
        "--group",
        "release",
        "python",
        "-m",
        "pytest",
        *(session.posargs or ["-q"]),
        external=True,
    )


@nox.session(python=DEFAULT_PYTHON, tags=["docs"], download_python="always")
def docs(session: nox.Session) -> None:
    """Build the documentation site in strict mode."""
    _sync(session)
    session.run("mkdocs", "build", "--strict", env={"DISABLE_MKDOCS_2_WARNING": "true"})


@nox.session(python=DEFAULT_PYTHON, tags=["release"], download_python="always")
def release(session: nox.Session) -> None:
    """Build, validate, install, and import release artifacts."""
    _sync(session, install_project=False)
    dist_dir = Path(session.create_tmp()) / "dist"
    session.run("python", "-m", "build", "--outdir", str(dist_dir))

    artifacts = sorted(dist_dir.iterdir())
    session.run("twine", "check", *(str(artifact) for artifact in artifacts))

    wheel = next(dist_dir.glob("*.whl"))
    session.install("--reinstall-package", "benchmatrix", str(wheel))
    session.run(
        "python",
        "-c",
        "from benchmatrix import BenchmarkCase; print(BenchmarkCase.__name__)",
    )
