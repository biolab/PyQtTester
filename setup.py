#!/usr/bin/env python

from setuptools import setup, find_packages

VERSION = '0.1.0'

if __name__ == '__main__':
    setup(
        name="PyQtTester",
        description="Test Python Qt (PyQt) applications",
        version=VERSION,
        author='Bioinformatics Laboratory, FRI UL',
        author_email='info@biolab.si',
        url='https://github.com/biolab/PyQtTester',
        keywords=(
            'PyQt', 'testing', 'TDD'
        ),
        packages=find_packages(),
        include_package_data=True,
        install_requires=(
        ),
        entry_points={
            'console_scripts': (
                'PyQtTester = pyqttester:main',
            ),
        }
    )
