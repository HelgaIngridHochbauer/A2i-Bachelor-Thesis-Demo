# coding=utf-8
"""Dialog test.

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""

__author__ = 'frincu.marc@gmail.com'
__date__ = '2021-10-30'
__copyright__ = 'Copyright 2021, Marc Frincu, Stefania Ionescu'

import os
import tempfile
import unittest

from qgis.PyQt.QtGui import QDialogButtonBox, QDialog

from dialog import Ui_Dialog

from utilities import get_qgis_app
QGIS_APP = get_qgis_app()


class ArchaeoAstroInsightDialogTest(unittest.TestCase):
    """Test settings dialog works."""

    def setUp(self):
        """Runs before each test."""
        self.tmpdir = tempfile.mkdtemp()
        # Ui_Dialog expects config.txt in path
        config_path = os.path.join(self.tmpdir, "config.txt")
        with open(config_path, "w") as f:
            f.write(self.tmpdir + "\n")
            f.write("\n\nNo\n\n0.7\n4\n")
        self.dialog = Ui_Dialog(self.tmpdir)

    def tearDown(self):
        """Runs after each test."""
        self.dialog = None
        try:
            import shutil
            shutil.rmtree(self.tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_dialog_ok(self):
        """Test we can click OK."""
        button = self.dialog.buttonBox.button(QDialogButtonBox.Ok)
        button.click()
        result = self.dialog.result()
        self.assertEqual(result, QDialog.Accepted)

    def test_dialog_cancel(self):
        """Test we can click cancel."""
        button = self.dialog.buttonBox.button(QDialogButtonBox.Cancel)
        button.click()
        result = self.dialog.result()
        self.assertEqual(result, QDialog.Rejected)


if __name__ == "__main__":
    suite = unittest.makeSuite(ArchaeoAstroInsightDialogTest)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
