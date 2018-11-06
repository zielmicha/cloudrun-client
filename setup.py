#!/usr/bin/env python
# coding=utf-8
from distutils.core import setup
import setuptools

setup(
    name='cloudrun',
    version='0.2.1',
    description='Client utility for cloudrun.io',
    author='The Cloudrun Authors',
    author_email='contact@cloudrun.io',
    url='https://cloudrun.io',
    packages=['cloudrun'],
    #scripts=['scripts/cloudrun'],
    entry_points={
        'console_scripts': ['cloudrun=cloudrun.client:main'],
    },
    install_requires=['requests>=2.9'],
    include_package_data=True,
    zip_safe=False,
)
