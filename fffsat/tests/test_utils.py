#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2017, Panu Lahtinen / FMI
#
# Author(s):
#
#   Panu Lahtinen <panu.lahtinen@fmi.fi>


"""Unit testing for foo
"""

import sys
import os.path
from collections import OrderedDict

from fffsat import utils

from posttroll.message import Message

if sys.version_info < (2, 7):
    import unittest2 as unittest
else:
    import unittest

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO


class TestUtils(unittest.TestCase):

    yaml_config = """config:
    item_1: 1
    item_2: 2
    """

    def test_ordered_load(self):
        fid = StringIO(self.yaml_config)
        res = utils.ordered_load(fid)
        fid.close()
        self.assertTrue(list(res.keys())[0] == "config")
        keys = list(res["config"].keys())
        self.assertTrue(keys[0] == "item_1")
        self.assertTrue(res["config"][keys[0]] == 1)
        self.assertTrue(keys[1] == "item_2")
        self.assertTrue(res["config"][keys[1]] == 2)

    def test_read_config(self):
        config = utils.read_config(os.path.join(os.path.dirname(__file__),
                                                "test_data", "config.yaml"))
        self.assertTrue(len(config) > 0)
        keys = config.keys()
        self.assertTrue(isinstance(config, OrderedDict))
        self.assertEqual(keys[0], 'item_1')
        self.assertTrue(isinstance(config['item_1'], str))
        self.assertTrue(isinstance(config['item_2'], list))
        self.assertTrue(isinstance(config['item_3'], OrderedDict))
        self.assertTrue(isinstance(config['item_4'], int))

    def test_get_filenames_from_msg(self):
        cma_pattern = "S_NWC_CMA_{platform_name}_{orbit:5d}_{start_time:%Y%m%dT%H%M%S}{foo}Z_{end_time:%Y%m%dT%H%M%S}{bar}Z.nc"
        l1b_pattern = "avhrr_{platform_name}_{start_time:%Y%m%d_%H%M}_{orbit}.l1b"
        config = {"data_fname_pattern": l1b_pattern,
                  "cloud_mask_fname_pattern": cma_pattern}
        cma_fname = "/tmp/S_NWC_CMA_noaa19_41474_20170224T1130341Z_20170224T1146098Z.nc"
        l1b_fname = "/tmp/avhrr_metop01_20170612_0949_24560.l1b"

        # Both files
        dataset = {"dataset": [{"uri": cma_fname}, {"uri": l1b_fname}]}
        msg = Message("/topic", "dataset", dataset)
        sat, cma = utils.get_filenames_from_msg(msg, config)
        self.assertEqual(sat, l1b_fname)
        self.assertEqual(cma, cma_fname)

        # Only satellite file
        dataset = {"dataset": [{"uri": l1b_fname}]}
        msg = Message("/topic", "dataset", dataset)
        sat, cma = utils.get_filenames_from_msg(msg, config)
        self.assertEqual(sat, l1b_fname)
        self.assertIsNone(cma)

        # Only cloud mask file
        dataset = {"dataset": [{"uri": cma_fname}]}
        msg = Message("/topic", "dataset", dataset)
        sat, cma = utils.get_filenames_from_msg(msg, config)
        self.assertEqual(cma, cma_fname)
        self.assertIsNone(sat)

        # No files
        dataset = {"dataset": []}
        msg = Message("/topic", "dataset", dataset)
        sat, cma = utils.get_filenames_from_msg(msg, config)
        self.assertIsNone(cma)
        self.assertIsNone(sat)


def suite():
    """The suite for test_utils
    """
    loader = unittest.TestLoader()
    mysuite = unittest.TestSuite()
    mysuite.addTest(loader.loadTestsFromTestCase(TestUtils))

    return mysuite

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite())