"""
Build configuration lives in pyproject.toml (source of truth).
setup.py is a compat shim for pip editable installs (<21.3) and legacy tooling.

When adding new metadata, add it to pyproject.toml FIRST, then mirror here.
"""
from setuptools import setup, find_namespace_packages

setup(
    name="a2e-python-sdk",
    version="0.1",
    description="Agent-to-Environment Protocol - Python SDK",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="Cynepia Technologies",
    license="MIT",
    python_requires=">=3.10",
    packages=find_namespace_packages(include=["a2e", "a2e.*"]),
    install_requires=[
        "pydantic==2.12.5",
        "fastmcp==3.2.0",
        "mcp==1.27.0",
        "fastapi==0.135.3",
        "uvicorn",
        "pyyaml",
    ],
    extras_require={"dev": ["setuptools"]},
    package_data={"": ["*.yaml", "*.yml"]},
    include_package_data=True,
    zip_safe=False,
)