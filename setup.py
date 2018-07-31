# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from setuptools import setup, find_packages

long_description = """
This library implements a convenient client for MazeRunner™ API for Python.
Using this library, you will be able to easily configure and manipulate the key features
of MazeRunner, such as the creation of a deception campaign, turning decoys on or off, deployment on
remote endpoints, and inspecting alerts with their attached evidence.

See the documentation at https://community.cymmetria.com/api

Fork us at https://github.com/Cymmetria/mazerunner_sdk_python
"""

setup(
    name='mazerunner_sdk',
    packages=find_packages(),
    version='1.2.3',
    description='MazeRunner SDK',
    long_description=long_description,
    author='Cymmetria',
    author_email='publicapi@cymmetria.com',
    url='https://github.com/Cymmetria/mazerunner_sdk_python',
    download_url='https://github.com/Cymmetria/mazerunner_sdk_python/tarball/1.2.3',
    license='BSD 3-Clause',
    keywords=['cymmetria', 'mazerunner', 'sdk', 'api'],
    install_requires=["argparse==1.2.1",
                      "mohawk==0.3.4",
                      "requests==2.13.0",
                      "requests-hawk==1.0.0",
                      "six==1.10.0",
                      "wsgiref==0.1.2"],
    classifiers=[],
)
