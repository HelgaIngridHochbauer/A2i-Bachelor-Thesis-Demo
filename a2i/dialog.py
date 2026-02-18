from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
import os.path

#Set parameters GUI
FORM_CLASS1, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__),'dialog.ui'))
class Ui_Dialog(QtWidgets.QDialog, FORM_CLASS1):
    def __init__(self, path, parent=None):
        self.path = path
        self.ui_path = os.path.join(path, "dialog.ui")
        self.config_path = os.path.join(path, "config.txt")

        super(Ui_Dialog, self).__init__(parent)
        uic.loadUi(self.ui_path, self)

        self.comboBox.addItem("Roadmap")
        self.comboBox.addItem("Terrain")
        self.comboBox.addItem("Satellite")
        self.comboBox.addItem("Hybrid")

        with open(self.config_path, 'r') as f:
            f.readline()
            self.resultsLine.setText(f.readline().rstrip("\n"))
            self.pythonLine.setText(f.readline().rstrip("\n"))

            if f.readline().rstrip("\n") == "Yes":
                self.checkBox.setChecked(True)
                self.comboBox.setCurrentText(f.readline().rstrip("\n"))
            else:
                self.checkBox.setChecked(False)
                f.readline()

            self.widthLine.setText(f.readline().rstrip("\n"))

            self.sleepLine.setText(f.readline().rstrip("\n"))

            srtm_line = f.readline().rstrip("\n") if f.readable() else ""
            if srtm_line and srtm_line != "Empty":
                self.srtmLine.setText(srtm_line)
            else:
                self.srtmLine.setText("")


    @pyqtSlot( )
    def resultsSlot( self ):
        home = self.path
        dir_path = QFileDialog.getExistingDirectory(self, "Choose Directory", home)

        self.resultsLine.setText(dir_path)

    @pyqtSlot( )
    def pythonSlot( self ):
        home = self.path
        dir_path = QFileDialog.getExistingDirectory(self, "Choose Directory", home)

        self.pythonLine.setText(dir_path)

    @pyqtSlot()
    def srtmSlot(self):
        home = self.srtmLine.text() if self.srtmLine.text() else self.path
        dir_path = QFileDialog.getExistingDirectory(self, "Choose SRTM Data Folder", home)
        if dir_path:
            self.srtmLine.setText(dir_path)

    @pyqtSlot()
    def srtmClearSlot(self):
        self.srtmLine.setText("")

    @pyqtSlot()
    def stateChangedSlot(self):
        if self.checkBox.isChecked():
            self.comboBox.setEnabled(True)
        else:
            self.comboBox.setEnabled(False)

    @pyqtSlot()
    def accept(self):
        with open(self.config_path, 'w') as f:
            f.write(self.path)

            f.write('\n')

            if self.resultsLine.text():
                f.write(self.resultsLine.text())
            else:
                f.write("Empty")

            f.write('\n')

            if self.pythonLine.text():
                test = self.pythonLine.text()
                if "python" in test.lower() or "python.exe" in test.lower():
                    f.write(test)
                else:
                    # Try to find python executable in the directory
                    python_exe = "python.exe" if os.name == 'nt' else "python"
                    f.write(os.path.join(self.pythonLine.text(), python_exe))
            else:
                f.write("Empty")

            f.write('\n')

            if self.checkBox.isChecked():
                f.write("Yes")
                f.write('\n')
                f.write(self.comboBox.currentText())
            else:
                f.write("No")
                f.write('\n')
                f.write("No Map")

            f.write('\n')

            if self.widthLine.text():
                f.write(self.widthLine.text())
            else:
                f.write(str(0.5))

            f.write('\n')

            if self.sleepLine.text():
                f.write(self.sleepLine.text())
            else:
                f.write(str(2))

            f.write('\n')

            if self.srtmLine.text():
                f.write(self.srtmLine.text())
            else:
                f.write("Empty")

        self.close()