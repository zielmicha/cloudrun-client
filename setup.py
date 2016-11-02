#!/usr/bin/env python
# coding=utf-8
from distutils.core import setup

setup(
    name='cloudrun',
    version='0.1.2',
    description='Client utility for cloudrun.io',
    author='Michał Zieliński',
    author_email='michal@zielinscy.org.pl',
    url='https://cloudrun.io',
    packages=['cloudrun'],
    scripts=['scripts/cloudrun'],
    install_requires=['requests', 'typing'],
)
