# coding=utf-8
"""Resources test.

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""

__author__ = 'frincu.marc@gmail.com'
__date__ = '2021-10-30'
__copyright__ = 'Copyright 2021, Marc Frincu, Stefania Ionescu'

import unittest

from qgis.PyQt.QtGui import QIcon



class ArchaeoAstroInsightDialogTest(unittest.TestCase):
    """Test rerources work."""

    def setUp(self):
        """Runs before each test."""
        pass

    def tearDown(self):
        """Runs after each test."""
        pass

    def test_icon_png(self):
        """Test plugin icon (logo) loads from compiled resources, same path as in a2i.py/core.py."""
        path = ':/plugins/a2i/logo/icons/logo.png'
        icon = QIcon(path)
        self.assertFalse(icon.isNull())

if __name__ == "__main__":
    suite = unittest.makeSuite(ArchaeoAstroInsightDialogTest)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)



