#!/usr/bin/env python

from setuptools import setup, find_packages
from pyqttester import __version__


if __name__ == '__main__':
    setup(
        name="PyQtTester",
        description="Test Python Qt (PyQt) applications",
        version=__version__,
        author='Bioinformatics Laboratory, FRI UL',
        author_email='contact@orange.biolab.si',
        url='https://github.com/biolab/PyQtTester',
        keywords=(
            'PyQt', 'testing', 'TDD'
        ),
        packages=find_packages(),
        py_modules=(
            'pyqttester',
        ),
        package_data={
        },
        install_requires=(
        ),
        entry_points={
            'console_scripts': (
                'PyQtTester = pyqttester:main',
            ),
        }
    )
