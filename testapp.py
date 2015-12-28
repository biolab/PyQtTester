#!/usr/bin/env python

import sys

from PyQt4 import QtCore, QtGui


def make_handler(i):
    def handler():
        print('Button {} was pressed'.format(i))
    return handler


def main():
    print('TestApp argv:', sys.argv)
    app = QtGui.QApplication([])
    dialog = QtGui.QDialog()
    dialog.setLayout(QtGui.QVBoxLayout())

    button1 = QtGui.QPushButton('Click me1', dialog, objectName='but1')
    button1.pressed.connect(make_handler(1))
    dialog.layout().addWidget(button1)

    button2 = QtGui.QPushButton('Click me2', dialog, objectName='but2')
    button2.pressed.connect(make_handler(2))
    dialog.layout().addWidget(button2)

    dialog.show()

    # When the app is tested with PyQtTester, the exit here is skipped ...
    sys.exit(app.exec())
    # ... this is printed instead.
    print('TestApp says: Bye bye.')


if __name__ == '__main__':
    main()
