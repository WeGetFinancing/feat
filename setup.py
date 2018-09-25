#!/usr/bin/env python
# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
from setuptools import setup, find_packages

try:  # for pip >= 10
    from pip._internal.req import parse_requirements
    from pip._internal.download import PipSession
except ImportError:  # for pip <= 9.0.3
    from pip.req import parse_requirements
    from pip.download import PipSession

import os

__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))

with open('README.md') as readme_file:
    readme = readme_file.read()


# with open('HISTORY.rst') as history_file:
#     history = history_file.read()

def read_requirements():
    '''parses requirements from requirements.txt'''
    try:
        reqs_path = os.path.join(__location__, 'requirements.txt')
        install_reqs = parse_requirements(reqs_path, session=PipSession())
        # We have to filter out git+ssh as them appear as None, causing the whole install to explode
        reqs = [str(ir.req) for ir in install_reqs if ir.req is not None]
    except Exception:
        # FIXME
        # This is crashing on my side!? make test-all does not work.
        reqs = []
    return reqs


setup_requirements = []

test_requirements = []

description = 'Flumotion Asynchronous Autonomous Agent Toolkit'

setup(
    author='Flumotion Developers, GetFinancing Development Team',
    author_email='it@getfinancing.com',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Environment :: No Input/Output (Daemon)',
        'License :: OSI Approved :: GNU General Public License (GPL)',
        'Operating System :: POSIX :: Linux',
        'Topic :: Software Development :: Libraries :: Application Frameworks'
        "Programming Language :: Python :: 2",
        'Programming Language :: Python :: 2.7',
    ],
    platforms=['any'],
    description=description,
    license='GPL',
    install_requires=read_requirements(),
    long_description=readme,  # + '\n\n' + history,
    long_description_content_type="text/markdown",
    include_package_data=True,
    keywords=['twisted', 'agent', 'framework'],
    name='feat',
    package_dir={'': 'src'},
    packages=find_packages('src'),
    scripts=['bin/feat',
             'bin/feat-service',
             'bin/feat-couchpy',
             'bin/feat-dbload',
             'bin/feat-locate'],
    setup_requires=setup_requirements,
    test_suite='tests',
    tests_require=test_requirements,
    url='https://github.com/GetFinancing/feat',
    version='18.38.dev1',
    zip_safe=False,
)
