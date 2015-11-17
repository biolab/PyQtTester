#!/usr/bin/env python

from PyQt4 import QtCore, QtGui


def main():
    app = QtGui.QApplication([])
    dialog = QtGui.QDialog()
    button = QtGui.QPushButton('Click me', dialog)
    dialog.show()
    app.exec_()


if __name__ == '__main__':
    main()
