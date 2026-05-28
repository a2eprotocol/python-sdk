import os
from setuptools import setup, find_namespace_packages
import pkg_resources
import pathlib

with pathlib.Path('requirements.txt').open() as requirements_txt:
    reqs = [
        str(requirement)
        for requirement
        in pkg_resources.parse_requirements(requirements_txt)
    ]

def _read(path):
    with open(path) as f:
        data = f.read()
    f.close()

    return data

README = ''
CHANGES = ''

setup(
    name='a2e-python-sdk',
    version='0.1',
    description='Agent-to-Environment Protocol - Python SDK',
    author='Cynepia Technologies',
    author_email='admin', license='MIT',
    packages=find_namespace_packages(include="a2e.*"),
    install_requires=reqs,
    package_data = {
      '': ['*.yaml', '*.yml'],
    },
    include_package_data = True,
    zip_safe=False
)
