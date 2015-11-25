#!/usr/bin/env python

from PyQt4 import QtCore, QtGui


def main():
    import sys
    print(sys.argv)
    app = QtGui.QApplication([])
    dialog = QtGui.QDialog()
    dialog.setLayout(QtGui.QVBoxLayout())
    button1 = QtGui.QPushButton('Click me1', dialog, objectName='but1')
    button2 = QtGui.QPushButton('Click me2', dialog, objectName='but2')
    dialog.layout().addWidget(button1)
    dialog.layout().addWidget(button2)
    dialog.show()
    print(app.topLevelWidgets())
    print(dialog.findChildren(QtGui.QPushButton))
    app.exec_()


if __name__ == '__main__':
    main()
