PyQtTester
===============================================================

PyQtTester is a tool for testing Python Qt (PyQt) GUI applications.

The testing is performed by, first, recording oneself clicking around on
the various UI widgets in their GUI application into test case units called
_scenarios_. Afterwards, one lets PyQtTester replay those scenarios.

PyQtTester is (supposed to be) friends with your continuous integration (CI)
environment.

**Note**: Currently tested with **Python 3** and Riverbank Computing's
**PyQt** _only_ (no Python 2.7, no PySide). Pull requests for PySide welcome!


Installation
------------
To install, system-wide, the latest developmental version:

    sudo pip install git+https://github.com/biolab/PyQtTester.git

or, to use the latest developmental version without installing:

    git clone git@github.com:biolab/PyQtTester.git
    cd PyQtTester
    ./pyqttester.py --help

Platforms besides GNU/Linux are not known to work. But on Unices, it might.


Usage
-----
Please RTFM (`--help`). Most generally, you record the scenario:

    PyQtTester record test-some-features.scenario myapp:main

And replay it afterwards:

    PyQtTester replay test-some-features.scenario myapp:main

But do use `--help` on the sub-commands as well!

Development
-----------
Please report bugs, along with their matching pull-requests, to:
https://github.com/biolab/PyQtTester/


FAQ
---
**Can it be made to work with Python 2.7 and/or PySide?**

Probably. Pull-requests welcome.

**Can it be made to work with my Qt C++ application?**

Unlikely. If it were, it would require a level of introspection and
Python-to-C++ glue magic the author is incapable of and not interested
in forging.

**How is this solution better than alternative Qt GUI testing solutions?**

Recording scenarios as macros, by giving example, instead of writing them in
a declarative (or otherwise) DSL, is fast and simple.

**How is this solution worse?**

The recorded scenario files are hard to interpret for a human:
When you record the scenario again (e.g. after some change that broke your
tests), make sure you test _all the same things_. Keep the scenarios small.
Use descriptive filenames. Also don't rely on it working.

**Why my apps so ugly?**

You coded them. Also because uniformity of testing environment. Think pixel
positions.

**Is there anything else I need to know?**

The app doesn't catch _any_ events on the native widgets/dialogs like the
file open dialog (`QFileDialog.getOpenFileName()`) and similar.

Also, if your `QObject` objects have their `objectName` set, make sure the
names are unique.
