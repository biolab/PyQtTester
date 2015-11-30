#!/usr/bin/env python

from PyQt4 import QtCore, QtGui

def handler():
    print('Button was pressed')


def main():
    import sys
    print('argv:', sys.argv)
    app = QtGui.QApplication([])
    dialog = QtGui.QDialog()
    dialog.setLayout(QtGui.QVBoxLayout())
    button1 = QtGui.QPushButton('Click me1', dialog, objectName='but1')
    # button2 = QtGui.QPushButton('Click me2', dialog, objectName='but2')
    button1.pressed.connect(handler)
    # button2.pressed.connect(handler)
    dialog.layout().addWidget(button1)
    # dialog.layout().addWidget(button2)
    dialog.show()
    print(app.topLevelWidgets())
    print(dialog.findChildren(QtGui.QPushButton))
    # QtCore.QTimer.singleShot(1000, lambda: asdf and app.quit())
    sys.exit(app.exec())
    print('after eight')



if __name__ == '__main__':
    main()
