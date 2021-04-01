#!/usr/bin/env python3
import os
from setuptools import setup, find_packages

# Utility function to read the README file.
# Used for the long_description.  It's nice, because now 1) we have a top level
# README file and 2) it's easier to type in the README file than to put a raw
# string in below ...
def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name="ghtt",
    version="0.0.1",
    author="Merlijn Sebrechts",
    author_email="merlijn.sebrechts@ugent.be",
    description=("ghtt helps teachers manage courses and exams that use GitHub."),
    license="AGPL",
    keywords="GitHub",
    url="http://packages.python.org/gh-teacher",
    packages=find_packages(),
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'ghtt = ghtt.__main__:cli',
        ],
    },
    long_description=read('README.md'),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Topic :: Utilities",
        "Natural Language :: English",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "License :: OSI Approved :: GNU Affero General Public License v3",
    ],
    install_requires=["github3.py", "pygithub", "click", "requests", "jinja2", "pyyaml", "tabulate"],
    python_requires='>=3.5',
)
